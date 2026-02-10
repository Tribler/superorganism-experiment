"""SSH-based deployment module for remote server provisioning."""

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple

import paramiko
from scp import SCPClient

logger = logging.getLogger(__name__)


class DeployerError(Exception):
    """Base exception for deployment operations."""
    pass


class SSHConnectionError(DeployerError):
    """Raised when SSH connection fails."""
    pass


class CommandError(DeployerError):
    """Raised when remote command fails."""
    pass


class Deployer:
    """SSH-based deployer for remote server setup and mycelium deployment."""

    MYCELIUM_REPO_URL = "https://github.com/Tribler/superorganism-experiment.git"
    MYCELIUM_SUBPATH = "self_replication_service__mycelium/mycelium"
    REMOTE_BASE_DIR = "/root/mycelium"
    REMOTE_MYCELIUM_DIR = f"{REMOTE_BASE_DIR}/{MYCELIUM_SUBPATH}"
    REMOTE_VENV_DIR = "/root/mycelium/venv"
    REMOTE_CONTENT_DIR = "/root/music"
    REMOTE_LOG_DIR = "/root/logs"
    REMOTE_DATA_DIR = "/root/data"

    def __init__(
        self,
        ssh_key_path: str,
        known_hosts_policy: str = "auto_add"
    ):
        """Initialize deployer. known_hosts_policy: 'auto_add', 'reject', or 'warn'."""
        self.ssh_key_path = Path(ssh_key_path)
        self.known_hosts_policy = known_hosts_policy

        self.client: Optional[paramiko.SSHClient] = None
        self.host: Optional[str] = None
        self.port: int = 22
        self.user: str = "root"

        if not self.ssh_key_path.exists():
            raise DeployerError(f"SSH key not found: {ssh_key_path}")

    def _load_private_key(self) -> paramiko.PKey:
        """Load SSH private key, auto-detecting the key type."""
        key_path = str(self.ssh_key_path)

        key_classes = [
            ("Ed25519", paramiko.Ed25519Key),
            ("RSA", paramiko.RSAKey),
            ("ECDSA", paramiko.ECDSAKey),
        ]

        last_error = None
        for key_name, key_class in key_classes:
            try:
                key = key_class.from_private_key_file(key_path)
                logger.debug(f"Loaded {key_name} key from {key_path}")
                return key
            except paramiko.SSHException:
                continue
            except Exception as e:
                last_error = e
                continue

        raise DeployerError(
            f"Failed to load SSH key from {key_path}. "
            f"Supported types: Ed25519, RSA, ECDSA. "
            f"Last error: {last_error}"
        )

    def connect(
        self,
        host: str,
        port: int = 22,
        user: str = "root",
        timeout: int = 30,
        retry_count: int = 3,
        retry_delay: int = 10
    ) -> None:
        """Establish SSH connection to remote server."""
        self.host = host
        self.port = port
        self.user = user

        self.client = paramiko.SSHClient()

        # Configure host key policy
        if self.known_hosts_policy == "auto_add":
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        elif self.known_hosts_policy == "warn":
            self.client.set_missing_host_key_policy(paramiko.WarningPolicy())
        else:
            self.client.set_missing_host_key_policy(paramiko.RejectPolicy())

        # Load private key (auto-detect key type)
        private_key = self._load_private_key()

        last_error = None
        for attempt in range(1, retry_count + 1):
            try:
                logger.info(f"Connecting to {user}@{host}:{port} (attempt {attempt}/{retry_count})")

                self.client.connect(
                    hostname=host,
                    port=port,
                    username=user,
                    pkey=private_key,
                    timeout=timeout,
                    allow_agent=False,
                    look_for_keys=False,
                )

                logger.info(f"Connected to {host}")
                return

            except Exception as e:
                last_error = e
                logger.warning(f"Connection attempt {attempt} failed: {e}")
                if attempt < retry_count:
                    logger.info(f"Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)

        raise SSHConnectionError(f"Failed to connect after {retry_count} attempts: {last_error}")

    def disconnect(self) -> None:
        if self.client:
            self.client.close()
            self.client = None
            logger.info(f"Disconnected from {self.host}")

    def run_command(
        self,
        command: str,
        timeout: int = 300,
        check: bool = True,
        background: bool = False
    ) -> Tuple[str, str, int]:
        """Execute command on remote server. Returns (stdout, stderr, exit_code)."""
        if not self.client:
            raise DeployerError("Not connected. Call connect() first.")

        logger.debug(f"Running: {command}")

        stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)

        if background:
            # Don't wait for exit status on background commands
            return "", "", 0

        exit_code = stdout.channel.recv_exit_status()

        stdout_text = stdout.read().decode("utf-8")
        stderr_text = stderr.read().decode("utf-8")

        if check and exit_code != 0:
            raise CommandError(
                f"Command failed with exit code {exit_code}: {command}\n"
                f"stderr: {stderr_text}"
            )

        return stdout_text, stderr_text, exit_code

    def upload_file(self, local_path: str, remote_path: str) -> None:
        if not self.client:
            raise DeployerError("Not connected. Call connect() first.")

        logger.info(f"Uploading {local_path} -> {remote_path}")

        with SCPClient(self.client.get_transport()) as scp:
            scp.put(local_path, remote_path)

    def upload_directory(self, local_path: str, remote_path: str) -> None:
        """Upload a directory using rsync over SSH."""
        logger.info(f"Uploading directory {local_path} -> {remote_path}")

        # Ensure remote directory exists
        self.run_command(f"mkdir -p {remote_path}")

        # Use rsync for efficient directory sync
        rsync_cmd = [
            "rsync", "-avz", "--progress",
            "-e", f"ssh -i {self.ssh_key_path} -p {self.port} -o StrictHostKeyChecking=no",
            f"{local_path}/",
            f"{self.user}@{self.host}:{remote_path}/"
        ]

        logger.debug(f"Running: {' '.join(rsync_cmd)}")
        result = subprocess.run(rsync_cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise DeployerError(f"rsync failed: {result.stderr}")

        logger.info("Directory upload complete")

    def download_file(self, remote_path: str, local_path: str) -> None:
        if not self.client:
            raise DeployerError("Not connected. Call connect() first.")

        logger.info(f"Downloading {remote_path} -> {local_path}")

        with SCPClient(self.client.get_transport()) as scp:
            scp.get(remote_path, local_path)

    def install_dependencies(self) -> None:
        """Install system dependencies (Python3, pip, git, libsodium-dev)."""
        logger.info("Installing system dependencies...")
        self.run_command("apt-get update -y", timeout=120)

        packages = [
            "python3",
            "python3-pip",
            "python3-venv",
            "git",
            "libsodium-dev",
            "build-essential",
        ]

        self.run_command(
            f"apt-get install -y {' '.join(packages)}",
            timeout=300
        )

        logger.info("System dependencies installed")

    def setup_firewall(self, extra_ports: Optional[list] = None) -> None:
        """Configure UFW firewall: SSH, BitTorrent ports, plus any extra_ports."""
        logger.info("Configuring firewall...")
        self.run_command("apt-get install -y ufw", timeout=60)
        self.run_command("ufw --force reset", check=False)
        self.run_command("ufw default deny incoming")
        self.run_command("ufw default allow outgoing")
        self.run_command("ufw allow 22/tcp comment 'SSH'")
        self.run_command("ufw allow 6881:6889/udp comment 'BitTorrent DHT'")
        self.run_command("ufw allow 6881:6999/tcp comment 'BitTorrent'")

        if extra_ports:
            for port in extra_ports:
                self.run_command(f"ufw allow {port}")
                logger.info(f"Allowed extra port: {port}")

        self.run_command("ufw --force enable")
        stdout, _, _ = self.run_command("ufw status verbose", check=False)
        logger.info(f"Firewall status:\n{stdout}")

        logger.info("Firewall configured successfully")

    def deploy_mycelium(
        self,
        repo_url: Optional[str] = None,
        branch: str = "main",
        subpath: Optional[str] = None
    ) -> None:
        """Clone and set up mycelium repository using sparse checkout from monorepo.

        The repo is cloned directly into REMOTE_BASE_DIR with sparse checkout,
        keeping the git working tree intact so that 'git pull' works for auto-updates.
        Files live at REMOTE_BASE_DIR/self_replication_service__mycelium/mycelium/.
        """
        repo_url = repo_url or self.MYCELIUM_REPO_URL
        subpath = subpath or self.MYCELIUM_SUBPATH

        logger.info(f"Deploying mycelium from {repo_url} (subpath: {subpath})")

        self.run_command(f"mkdir -p {self.REMOTE_CONTENT_DIR}")
        self.run_command(f"mkdir -p {self.REMOTE_LOG_DIR}")
        self.run_command(f"mkdir -p {self.REMOTE_DATA_DIR}")

        _, _, exit_code = self.run_command(
            f"test -d {self.REMOTE_BASE_DIR}/.git",
            check=False
        )

        if exit_code == 0:
            logger.info("Repository exists, pulling updates...")
            self.run_command(f"cd {self.REMOTE_BASE_DIR} && git pull origin {branch}")
        else:
            logger.info("Cloning repository with sparse checkout...")
            self.run_command(f"rm -rf {self.REMOTE_BASE_DIR}")
            self.run_command(
                f"git clone --filter=blob:none --sparse -b {branch} {repo_url} {self.REMOTE_BASE_DIR}",
                timeout=120
            )
            self.run_command(
                f"cd {self.REMOTE_BASE_DIR} && git sparse-checkout set {subpath}"
            )

        logger.info("Creating virtual environment...")
        self.run_command(f"python3 -m venv {self.REMOTE_VENV_DIR}")

        logger.info("Installing Python requirements...")
        self.run_command(
            f"{self.REMOTE_VENV_DIR}/bin/pip install -r {self.REMOTE_MYCELIUM_DIR}/code/requirements.txt",
            timeout=300
        )

        logger.info("Mycelium deployed successfully")

    def deploy_content(self, content_dir: str) -> None:
        """Upload content files to remote server."""
        logger.info(f"Deploying content from {content_dir}")

        if not Path(content_dir).exists():
            raise DeployerError(f"Content directory not found: {content_dir}")

        self.upload_directory(content_dir, self.REMOTE_CONTENT_DIR)
        logger.info("Content deployed successfully")

    def set_environment_variable(self, name: str, value: str) -> None:
        escaped_value = value.replace("'", "'\\''")
        self.run_command(f"echo \"{name}='{escaped_value}'\" >> /etc/environment")

    def start_orchestrator(self, bitcoin_xpub: Optional[str] = None) -> None:
        logger.info("Starting orchestrator...")

        env_vars = {
            "MYCELIUM_BASE_DIR": self.REMOTE_BASE_DIR,
            "MYCELIUM_VENV_DIR": self.REMOTE_VENV_DIR,
            "MYCELIUM_CONTENT_DIR": self.REMOTE_CONTENT_DIR,
            "MYCELIUM_LOG_DIR": self.REMOTE_LOG_DIR,
            "MYCELIUM_DATA_DIR": self.REMOTE_DATA_DIR,
        }

        if bitcoin_xpub:
            env_vars["MYCELIUM_BITCOIN_XPUB"] = bitcoin_xpub

        for name, value in env_vars.items():
            self.set_environment_variable(name, value)

        self.run_command("pkill -f 'python.*main.py' || true", check=False)

        code_dir = f"{self.REMOTE_MYCELIUM_DIR}/code"
        wrapper_script = f"{code_dir}/scripts/orchestrator_wrapper.sh"
        self.run_command(f"chmod +x {wrapper_script}")

        env_string = " ".join(f"{k}='{v}'" for k, v in env_vars.items())

        self.run_command(
            f"cd {code_dir} && "
            f"nohup env PATH=\"{self.REMOTE_VENV_DIR}/bin:$PATH\" {env_string} bash {wrapper_script} "
            f"< /dev/null > {self.REMOTE_LOG_DIR}/wrapper.log 2>&1 &",
            background=True
        )

        time.sleep(3)
        stdout, _, _ = self.run_command("pgrep -f 'python.*main.py' || echo 'not running'")

        if "not running" in stdout:
            raise DeployerError("Orchestrator failed to start")

        logger.info("Orchestrator started successfully")

    def check_health(self) -> bool:
        """Return True if orchestrator is running."""
        stdout, _, exit_code = self.run_command(
            "pgrep -f 'python.*main.py'",
            check=False
        )

        is_healthy = exit_code == 0 and stdout.strip()

        if is_healthy:
            logger.info("Health check passed")
        else:
            logger.warning("Health check failed - orchestrator not running")

        return is_healthy

    def get_logs(self, lines: int = 50) -> str:
        stdout, _, _ = self.run_command(
            f"tail -n {lines} {self.REMOTE_LOG_DIR}/orchestrator.log 2>/dev/null || echo 'No logs yet'",
            check=False
        )
        return stdout


def generate_ssh_keypair(
    key_path: str,
    key_type: str = "ed25519",
    comment: str = "mycelium-deploy"
) -> Tuple[str, str]:
    """Generate SSH keypair. Returns (private_key_path, public_key_content)."""
    key_path = Path(key_path)
    key_path.parent.mkdir(parents=True, exist_ok=True)

    if key_path.exists():
        key_path.unlink()
    pub_path = Path(f"{key_path}.pub")
    if pub_path.exists():
        pub_path.unlink()

    cmd = [
        "ssh-keygen",
        "-t", key_type,
        "-f", str(key_path),
        "-N", "",
        "-C", comment,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise DeployerError(f"Failed to generate SSH key: {result.stderr}")

    os.chmod(key_path, 0o600)

    with open(pub_path) as f:
        public_key = f.read().strip()

    logger.info(f"Generated SSH keypair: {key_path}")
    return str(key_path), public_key


