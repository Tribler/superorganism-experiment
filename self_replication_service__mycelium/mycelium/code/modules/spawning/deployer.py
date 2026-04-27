"""Orchestrates the full child-spawn pipeline with durable identity + VPS reuse on retry."""

import asyncio
from dataclasses import asdict

from config import Config
from utils import setup_logger
from ..core import state as state_module
from ..monitoring.node_monitor import NodeState
from .errors import SpawnError
from .spawn_deploy import boot_child_orchestrator, deploy_child_code
from .spawn_identity import ChildIdentity, prepare_child_identity
from .spawn_provision import ChildVpsInfo, provision_child_vps
from .spawn_transfer import transfer_inheritance

logger = setup_logger(__name__, log_file=Config.LOG_DIR / "orchestrator.log", level=Config.LOG_LEVEL)

_DISCONNECT_TIMEOUT_SECONDS = 15


def _load_stored_identity(ps, spawn_id: str):
    """If a matching identity blob was persisted by a prior attempt, rehydrate it."""
    blob = ps.get("spawn_identity")
    if not blob or blob.get("spawn_id") != spawn_id:
        return None
    try:
        return ChildIdentity(**blob)
    except TypeError as e:
        logger.warning("Stored identity blob has unexpected shape (%s) — discarding", e)
        ps.delete("spawn_identity")
        return None


def _load_stored_vps(ps, spawn_id: str):
    """If a matching VPS-info blob was persisted by a prior attempt, rehydrate it."""
    blob = ps.get("spawn_vps_info")
    if not blob or blob.get("spawn_id") != spawn_id:
        return None
    try:
        return ChildVpsInfo(**blob)
    except TypeError as e:
        logger.warning("Stored VPS-info blob has unexpected shape (%s) — discarding", e)
        ps.delete("spawn_vps_info")
        return None


_INTENT_KEYS = (
    "spawn_identity",
    "spawn_child_wallet",
    "spawn_sporestack_token",
    "spawn_funding_intent",
    "spawn_funding_txid",
    "spawn_vps_intent",
    "spawn_vps_info",
    "spawn_transfer_intent",
    "spawn_transfer_txid",
)


def _log_intent_summary(ps, spawn_id: str) -> None:

    present = []
    for key in _INTENT_KEYS:
        blob = ps.get(key)
        if blob is None:
            continue
        # Flat string values (txids) and dict values (intents) both count.
        if isinstance(blob, dict) and blob.get("spawn_id") not in (None, spawn_id):
            continue
        present.append(key)
    if present:
        logger.info("Resume state: persisted keys for spawn_id=%s → %s", spawn_id, present)
    else:
        logger.info("Fresh spawn: no persisted intent/result keys for spawn_id=%s", spawn_id)


async def _safe_disconnect(ssh_deployer) -> None:
    """Disconnect SSH off the event loop with a bounded timeout."""
    try:
        await asyncio.wait_for(
            asyncio.to_thread(ssh_deployer.disconnect),
            timeout=_DISCONNECT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("SSH disconnect timed out after %ds — abandoning socket", _DISCONNECT_TIMEOUT_SECONDS)
    except Exception as e:
        logger.warning("SSH disconnect raised: %s", e)


async def spawn_child(node_state: NodeState, caution_trait: float, spawn_id: str) -> bool:
    """Run the full spawn pipeline. Returns True on success, False on failure.

    On failure, leave spawn_in_progress=True for retry. Each durable side-effect
    (identity minting, VPS provisioning) persists its result to state.db so a restart
    mid-pipeline can re-enter at the last successful step without re-spending money
    on fresh SporeStack tokens or orphaning already-provisioned VPSes.
    """
    ps = state_module.get()
    if ps is None:
        logger.error("Persistent state unavailable — aborting spawn")
        return False

    ssh_deployer = None
    logger.info("=== Spawn pipeline start: spawn_id=%s ===", spawn_id)
    _log_intent_summary(ps, spawn_id)
    try:
        # Step 1: identity (reuse if already minted & funded)
        identity = _load_stored_identity(ps, spawn_id)
        if identity is not None:
            logger.info(
                "[1/5] Reusing persisted child identity: spawn_id=%s (sporestack_token funded=%d cents)",
                spawn_id, identity.funded_cents,
            )
        else:
            logger.info("[1/5] Preparing child identity: spawn_id=%s", spawn_id)
            identity = await prepare_child_identity(spawn_id, node_state)
            ps.set("spawn_identity", asdict(identity))

        # Step 2: VPS (reuse if already provisioned)
        vps_info = _load_stored_vps(ps, spawn_id)
        if vps_info is not None:
            logger.info(
                "[2/5] Reusing persisted child VPS: spawn_id=%s machine_id=%s host=%s:%d",
                spawn_id, vps_info.machine_id, vps_info.host, vps_info.ssh_port,
            )
        else:
            logger.info("[2/5] Provisioning child VPS: spawn_id=%s", spawn_id)
            vps_info = await provision_child_vps(identity)

        # Step 3: deploy code (always re-runs — idempotent thanks to git pull / mkdir -p etc.)
        logger.info(
            "[3/5] Deploying child code: spawn_id=%s host=%s",
            spawn_id, vps_info.host,
        )
        ssh_deployer = await deploy_child_code(identity, vps_info)

        # Step 4: boot orchestrator
        logger.info("[4/5] Booting child orchestrator: spawn_id=%s", spawn_id)
        child_caution = await boot_child_orchestrator(ssh_deployer, identity, caution_trait)

        # Step 5: transfer inheritance (mark_spawn_completed inside clears state keys + rmtree)
        logger.info("[5/5] Transferring inheritance BTC: spawn_id=%s", spawn_id)
        txid = await transfer_inheritance(identity, node_state)

        logger.info(
            "=== Spawn complete: spawn_id=%s child_btc=%s txid=%s caution=%.3f ===",
            spawn_id, identity.btc_address, txid, child_caution,
        )
        return True
    except SpawnError as e:
        logger.error(
            "Spawn pipeline failed at step=%s: spawn_id=%s — %s. "
            "spawn_in_progress=True preserved; will retry on next restart.",
            e.step, spawn_id, e,
        )
        return False
    except Exception:
        logger.exception(
            "Unexpected error in spawn pipeline: spawn_id=%s. "
            "spawn_in_progress=True preserved; will retry on next restart.",
            spawn_id,
        )
        return False
    finally:
        if ssh_deployer is not None:
            await _safe_disconnect(ssh_deployer)
