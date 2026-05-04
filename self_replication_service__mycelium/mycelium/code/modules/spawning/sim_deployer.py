"""
Sim-mode substitute for SSHDeployer. Mirrors SSHDeployer's public surface so
spawn_deploy.boot_child_orchestrator can dispatch polymorphically. The LXC
image baked in TODO 8.5 is pre-provisioned, so all container-prep methods
(connect, install_dependencies, setup_firewall, deploy_mycelium,
deploy_video_ids, deploy_cookies, disconnect) are no-ops; start_orchestrator
and check_health route through the mock SporeStack /sim/* endpoints (TODO 8.9).
"""

import json
import urllib.error
import urllib.request
from typing import Dict, Optional

from config import Config
from utils import setup_logger

logger = setup_logger(__name__, log_file=Config.LOG_DIR / "orchestrator.log", level=Config.LOG_LEVEL)


class SimDeployer:
    """LXC-backed deployer for the offline thesis sim. Interface-compatible with SSHDeployer."""

    REMOTE_DATA_DIR = "/root/data"

    def __init__(self, machine_id: str, base_url: str):
        self.machine_id = machine_id
        self.base_url = base_url.rstrip("/")
        self.host = machine_id

    def connect(self, host: str, port: int = 22, user: str = "root", **_kwargs) -> None:
        self.host = host
        logger.debug("SimDeployer.connect noop (machine_id=%s host=%s)", self.machine_id, host)

    def disconnect(self) -> None:
        logger.debug("SimDeployer.disconnect noop (machine_id=%s)", self.machine_id)

    def install_dependencies(self) -> None:
        logger.debug("SimDeployer.install_dependencies noop (image is pre-baked)")

    def setup_firewall(self, extra_ports: Optional[list] = None) -> None:
        logger.debug("SimDeployer.setup_firewall noop (no firewall in LXC sim)")

    def deploy_mycelium(
        self,
        repo_url: Optional[str] = None,
        branch: str = "main",
        subpath: Optional[str] = None,
    ) -> None:
        logger.debug("SimDeployer.deploy_mycelium noop (code is in the image)")

    def deploy_video_ids(self, local_path: str) -> None:
        logger.debug("SimDeployer.deploy_video_ids noop (seeding bypassed in sim)")

    def deploy_cookies(self, local_path: str) -> None:
        logger.debug("SimDeployer.deploy_cookies noop (seeding bypassed in sim)")

    def start_orchestrator(
        self,
        env: Optional[Dict[str, str]] = None,
        secrets: Optional[Dict[str, str]] = None,
    ) -> None:
        url = f"{self.base_url}/sim/start/{self.machine_id}"
        payload = json.dumps({"env": env or {}, "secrets": secrets or {}}).encode()
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status != 200:
                    body = resp.read().decode(errors="replace")
                    raise RuntimeError(
                        f"sim start_orchestrator failed: HTTP {resp.status} {body}"
                    )
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace") if hasattr(e, "read") else ""
            raise RuntimeError(
                f"sim start_orchestrator HTTPError {e.code}: {body}"
            ) from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"sim start_orchestrator URLError: {e}") from e

        logger.info("SimDeployer.start_orchestrator: machine_id=%s started", self.machine_id)

    def check_health(self) -> bool:
        url = f"{self.base_url}/sim/health/{self.machine_id}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    logger.warning(
                        "SimDeployer.check_health HTTP %d for machine_id=%s",
                        resp.status, self.machine_id,
                    )
                    return False
                data = json.loads(resp.read().decode())
        except Exception as e:
            logger.warning(
                "SimDeployer.check_health failed for machine_id=%s: %s",
                self.machine_id, e,
            )
            return False

        running = bool(data.get("running"))
        if running:
            logger.info("SimDeployer.check_health: machine_id=%s running", self.machine_id)
        else:
            logger.warning("SimDeployer.check_health: machine_id=%s not running", self.machine_id)
        return running
