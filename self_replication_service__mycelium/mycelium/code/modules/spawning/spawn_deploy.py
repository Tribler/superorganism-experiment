"""
Two-phase child VPS deployment over the same SSH session:
  deploy_child_code       — install deps, firewall, code + content files.
  boot_child_orchestrator — write secrets, inject env, start orchestrator.
Caller (deployer.spawn_child) owns the final disconnect.
"""

import asyncio
from typing import Union

from config import Config
from utils import setup_logger
from ..orchestration.spawn_thresholds import mutate_caution_trait
from .errors import SpawnError
from .sim_deployer import SimDeployer
from .spawn_identity import ChildIdentity
from .spawn_provision import ChildVpsInfo
from .ssh_deployer import SSHDeployer

logger = setup_logger(__name__, log_file=Config.LOG_DIR / "orchestrator.log", level=Config.LOG_LEVEL)

_POST_START_SETTLE_SECONDS = 15

ChildDeployer = Union[SSHDeployer, SimDeployer]


async def deploy_child_code(
    identity: ChildIdentity,
    vps_info: ChildVpsInfo,
) -> ChildDeployer:
    """SSH into child VPS, install deps, deploy code and content. Returns connected deployer (caller owns disconnect)."""
    if Config.SIM_MODE:
        logger.info(
            "Sim mode: returning SimDeployer for spawn_id=%s machine_id=%s (LXC image is pre-baked)",
            identity.spawn_id, vps_info.machine_id,
        )
        return SimDeployer(
            machine_id=vps_info.machine_id,
            base_url=Config.SPORESTACK_BASE_URL,
        )

    logger.info(
        "Deploying code to child VPS: spawn_id=%s host=%s:%d",
        identity.spawn_id, vps_info.host, vps_info.ssh_port,
    )

    deployer = SSHDeployer(ssh_key_path=vps_info.ssh_key_path)

    try:
        await asyncio.to_thread(
            deployer.connect, vps_info.host, port=vps_info.ssh_port
        )
        await asyncio.to_thread(deployer.install_dependencies)
        await asyncio.to_thread(deployer.setup_firewall)
        await asyncio.to_thread(deployer.deploy_mycelium)
        await asyncio.to_thread(
            deployer.deploy_video_ids, str(Config.VIDEO_IDS_FILE)
        )
        await asyncio.to_thread(
            deployer.deploy_cookies, str(Config.COOKIES_FILE)
        )
    except Exception as e:
        await asyncio.to_thread(deployer.disconnect)
        raise SpawnError(
            "deploy",
            f"Child code deployment failed for {identity.spawn_id}: {e}",
        ) from e

    logger.info(
        "Child code deployed: spawn_id=%s host=%s",
        identity.spawn_id, vps_info.host,
    )
    return deployer


async def boot_child_orchestrator(
    deployer: ChildDeployer,
    identity: ChildIdentity,
    parent_caution_trait: float,
) -> float:
    """Write secrets + env, start child orchestrator, verify it stays up. Returns mutated caution trait."""
    child_caution = mutate_caution_trait(parent_caution_trait)

    env = {
        "MYCELIUM_FRIENDLY_NAME": identity.spawn_id,
        "MYCELIUM_PARENT_NAME": Config.FRIENDLY_NAME,
        "MYCELIUM_CAUTION_TRAIT": f"{child_caution:.6f}",
        "MYCELIUM_CAUTION_MUTATION_SIGMA": str(Config.CAUTION_MUTATION_SIGMA),
        "MYCELIUM_SPAWN_THRESHOLD_DAYS": str(Config.SPAWN_THRESHOLD_DAYS),
        "MYCELIUM_SPAWN_RESERVE_DAYS": str(Config.SPAWN_RESERVE_DAYS),
        "MYCELIUM_INHERITANCE_RATIO": str(Config.INHERITANCE_RATIO),
    }
    if Config.LOG_ENDPOINT:
        env["MYCELIUM_LOG_ENDPOINT"] = Config.LOG_ENDPOINT
    if Config.LOG_SECRET:
        env["MYCELIUM_LOG_SECRET"] = Config.LOG_SECRET
    if Config.DEFAULT_BTC_ADDRESS:
        env["MYCELIUM_DEFAULT_BTC_ADDRESS"] = Config.DEFAULT_BTC_ADDRESS

    secrets = {
        f"{deployer.REMOTE_DATA_DIR}/btc_mnemonic_seed": identity.btc_mnemonic,
        f"{deployer.REMOTE_DATA_DIR}/sporestack_token": identity.sporestack_token,
    }

    try:
        await asyncio.to_thread(deployer.start_orchestrator, env=env, secrets=secrets)
        await asyncio.sleep(_POST_START_SETTLE_SECONDS)
        healthy = await asyncio.to_thread(deployer.check_health)
        if not healthy:
            raise SpawnError(
                "boot",
                f"Child orchestrator crashed within {_POST_START_SETTLE_SECONDS}s of boot",
            )
    except SpawnError:
        raise
    except Exception as e:
        raise SpawnError(
            "boot",
            f"Child orchestrator boot failed for {identity.spawn_id}: {e}",
        ) from e

    logger.info(
        "Child orchestrator running: spawn_id=%s caution=%.3f host=%s",
        identity.spawn_id, child_caution, deployer.host,
    )
    return child_caution
