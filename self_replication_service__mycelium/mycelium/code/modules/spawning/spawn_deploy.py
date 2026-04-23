"""
Two-phase child VPS deployment over the same SSH session:
  deploy_child_code       — install deps, firewall, code + content files.
  boot_child_orchestrator — write secrets, inject env, start orchestrator.
Caller (deployer.spawn_child) owns the final disconnect.
"""

import asyncio

from config import Config
from utils import setup_logger
from ..orchestration.spawn_thresholds import mutate_caution_trait
from .spawn_identity import ChildIdentity
from .spawn_provision import ChildVpsInfo
from .ssh_deployer import SSHDeployer

logger = setup_logger(__name__, log_file=Config.LOG_DIR / "orchestrator.log", level=Config.LOG_LEVEL)

_POST_START_SETTLE_SECONDS = 15


class SpawnDeployError(Exception):
    """Any failure during child code deployment or orchestrator boot."""
    pass


async def deploy_child_code(
    identity: ChildIdentity,
    vps_info: ChildVpsInfo,
) -> SSHDeployer:
    """SSH into child VPS, install deps, deploy code and content. Returns connected deployer (caller owns disconnect)."""
    logger.info(
        "Deploying code to child VPS: child_token=%s host=%s:%d",
        identity.child_token, vps_info.host, vps_info.ssh_port,
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
        deployer.disconnect()
        raise SpawnDeployError(
            f"Child code deployment failed for {identity.child_token}: {e}"
        ) from e

    logger.info(
        "Child code deployed: child_token=%s host=%s",
        identity.child_token, vps_info.host,
    )
    return deployer


async def boot_child_orchestrator(
    deployer: SSHDeployer,
    identity: ChildIdentity,
    parent_caution_trait: float,
) -> float:
    """Write secrets + env, start child orchestrator, verify it stays up. Returns mutated caution trait."""
    child_caution = mutate_caution_trait(parent_caution_trait)

    env = {
        "MYCELIUM_CAUTION_TRAIT": f"{child_caution:.6f}",
        "MYCELIUM_PARENT_NAME": Config.FRIENDLY_NAME,
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
            raise SpawnDeployError(
                f"Child orchestrator crashed within {_POST_START_SETTLE_SECONDS}s of boot"
            )
    except Exception as e:
        raise SpawnDeployError(
            f"Child orchestrator boot failed for {identity.child_token}: {e}"
        ) from e

    logger.info(
        "Child orchestrator running: child_token=%s caution=%.3f host=%s",
        identity.child_token, child_caution, deployer.host,
    )
    return child_caution
