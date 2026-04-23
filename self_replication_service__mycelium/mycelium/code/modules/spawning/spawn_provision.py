"""Provisions a child VPS via SporeStack and persists connection metadata for SSH deploy."""

import asyncio
from dataclasses import dataclass

from config import Config
from utils import setup_logger
from ..core import state as state_module
from ..monitoring import sporestack_client
from .spawn_identity import ChildIdentity

logger = setup_logger(__name__, log_file=Config.LOG_DIR / "orchestrator.log", level=Config.LOG_LEVEL)


class SpawnProvisionError(Exception):
    """Any failure during child VPS provisioning."""
    pass


@dataclass
class ChildVpsInfo:
    machine_id: str
    host: str           # picked from ipv4/ipv6 per bootstrap logic
    ipv4: str           # raw field kept for diagnostics
    ipv6: str           # raw field kept for diagnostics
    ssh_port: int
    ssh_key_path: str   # carried through from identity for 10.5 convenience


async def provision_child_vps(identity: ChildIdentity) -> ChildVpsInfo:
    ps = state_module.get()
    if ps is None:
        raise SpawnProvisionError("persistent state not initialised")

    logger.info(
        "Provisioning VPS for %s (hostname=%s, provider=%s, flavor=%s, region=%s)",
        identity.child_token, identity.child_token,
        Config.VPS_PROVIDER, Config.VPS_FLAVOR, Config.VPS_REGION,
    )

    machine_id = await asyncio.to_thread(
        sporestack_client.launch_server,
        identity.sporestack_token,
        identity.ssh_public_key,
        hostname=identity.child_token,
    )
    if not machine_id:
        raise SpawnProvisionError("launch_server returned no machine_id")

    server = await asyncio.to_thread(
        sporestack_client.wait_for_server_ready,
        identity.sporestack_token,
        machine_id,
    )
    if server is None:
        raise SpawnProvisionError(
            f"machine {machine_id} not ready within timeout"
        )

    ipv4 = server.get("ipv4") or ""
    ipv6 = server.get("ipv6") or ""
    has_ipv4 = bool(ipv4) and ipv4 != "0.0.0.0"
    has_ipv6 = bool(ipv6) and ipv6 not in ("", "::")
    host = ipv4 if has_ipv4 else (ipv6 if has_ipv6 else None)
    if host is None:
        raise SpawnProvisionError(
            f"machine {machine_id} has no usable IPv4/IPv6"
        )
    ssh_port = int(server.get("ssh_port", 22))

    ps.set("spawn_vps_info", {
        "child_token": identity.child_token,
        "machine_id": machine_id,
        "host": host,
        "ipv4": ipv4,
        "ipv6": ipv6,
        "ssh_port": ssh_port,
        "ssh_key_path": identity.ssh_private_key_path,
    })

    logger.info(
        "Child VPS ready: child_token=%s machine_id=%s host=%s:%d",
        identity.child_token, machine_id, host, ssh_port,
    )

    return ChildVpsInfo(
        machine_id=machine_id,
        host=host,
        ipv4=ipv4,
        ipv6=ipv6,
        ssh_port=ssh_port,
        ssh_key_path=identity.ssh_private_key_path,
    )
