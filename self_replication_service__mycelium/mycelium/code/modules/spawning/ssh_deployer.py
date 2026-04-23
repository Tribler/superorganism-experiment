"""SSH-based deployment mechanics for provisioning child mycelium nodes."""

import os
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

import paramiko
from scp import SCPClient

from config import Config
from utils import setup_logger

logger = setup_logger(__name__, log_file=Config.LOG_DIR / "orchestrator.log", level=Config.LOG_LEVEL)


class DeployerError(Exception):
    """Base exception for deployment operations."""
    pass


class SSHConnectionError(DeployerError):
    """Raised when SSH connection fails."""
    pass


class CommandError(DeployerError):
    """Raised when remote command fails."""
    pass


class SSHDeployer:
    """SSH-based deployer for remote server setup and mycelium deployment."""

    MYCELIUM_REPO_URL = "https://github.com/Tribler/superorganism-experiment.git"
    MYCELIUM_SUBPATH = "self_replication_service__mycelium/mycelium"
    REMOTE_BASE_DIR = "/root/mycelium"
    REMOTE_MYCELIUM_DIR = f"{REMOTE_BASE_DIR}/{MYCELIUM_SUBPATH}"
    REMOTE_VENV_DIR = "/root/mycelium/venv"
    REMOTE_CONTENT_DIR = "/root/music"
    REMOTE_LOG_DIR = "/root/logs"
    REMOTE_DATA_DIR = "/root/data"
    REMOTE_VIDEO_IDS_FILE = "/root/cc_video_ids.txt"
    REMOTE_COOKIES_FILE = "/root/yt_cookies.txt"

    def __init__(
        self,
        ssh_key_path: str,
        known_hosts_policy: str = "auto_add"
    ):
        """Initialize deployer. known_hosts_policy: 'auto_add', 'reject', or 'warn'."""
        self.ssh_key_path = Path(ssh_key_path)
        self.known_hosts_policy = known_hosts_policy

        self.known_hosts_path = Path.home() / ".mycelium" / "known_hosts"

        self.client: Optional[paramiko.SSHClient] = None
        self.host: Optional[str] = None
        self.port: int = 22
        self.user: str = "root"

        if not self.ssh_key_path.exists():
            raise DeployerError(f"SSH key not found: {ssh_key_path}")

    def _write_secret_file(self, content: str, remote_path: str) -> None:
        """Write secret content to a remote file via stdin (never touches command line)."""
        stdin, stdout, stderr = self.client.exec_command(
            f"( umask 177 && cat > {remote_path} )"
        )
        stdin.write(content.encode())
        stdin.channel.shutdown_write()
        if stdout.channel.recv_exit_status() != 0:
            raise CommandError(f"Failed to write secret file: {stderr.read().decode()}")

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
                logger.debug("Loaded %s key from %s", key_name, key_path)
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

        # TOFU host key pinning
        self.known_hosts_path.parent.mkdir(parents=True, exist_ok=True)
        if self.known_hosts_path.exists():
            self.client.load_host_keys(str(self.known_hosts_path))

        host_known = self.client.get_host_keys().lookup(host) is not None
        if host_known:
            self.client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        private_key = self._load_private_key()

        last_error = None
        for attempt in range(1, retry_count + 1):
            try:
                logger.info("Connecting to %s@%s:%d (attempt %d/%d)", user, host, port, attempt, retry_count)

                self.client.connect(
                    hostname=host,
                    port=port,
                    username=user,
                    pkey=private_key,
                    timeout=timeout,
                    allow_agent=False,
                    look_for_keys=False,
                )

                self.client.save_host_keys(str(self.known_hosts_path))
                logger.info("Connected to %s", host)
                return

            except Exception as e:
                last_error = e
                logger.warning("Connection attempt %d failed: %s", attempt, e)
                if attempt < retry_count:
                    logger.info("Retrying in %ds...", retry_delay)
                    time.sleep(retry_delay)

        raise SSHConnectionError(f"Failed to connect after {retry_count} attempts: {last_error}")

    def disconnect(self) -> None:
        if self.client:
            self.client.close()
            self.client = None
            logger.info("Disconnected from %s", self.host)

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

        logger.debug("Running: %s", command)

        stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)

        if background:
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

        logger.info("Uploading %s -> %s", local_path, remote_path)

        with SCPClient(self.client.get_transport()) as scp:
            scp.put(local_path, remote_path)

    def upload_directory(self, local_path: str, remote_path: str) -> None:
        """Upload a directory using rsync over SSH."""
        logger.info("Uploading directory %s -> %s", local_path, remote_path)

        self.run_command(f"mkdir -p {remote_path}")

        rsync_cmd = [
            "rsync", "-avz", "--progress",
            "-e", f"ssh -i {self.ssh_key_path} -p {self.port} -o StrictHostKeyChecking=yes -o UserKnownHostsFile={self.known_hosts_path}",
            f"{local_path}/",
            f"{self.user}@{self.host}:{remote_path}/"
        ]

        logger.debug("Running: %s", ' '.join(rsync_cmd))
        result = subprocess.run(rsync_cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise DeployerError(f"rsync failed: {result.stderr}")

        logger.info("Directory upload complete")

    def _wait_for_apt_lock(self, timeout: int = 300) -> None:
        """Wait for apt/dpkg locks to be released (e.g. after fresh VPS boot)."""
        logger.info("Waiting for apt lock...")
        self.run_command(
            f"timeout {timeout} bash -c "
            f"'while fuser /var/lib/dpkg/lock-frontend /var/lib/apt/lists/lock "
            f"/var/lib/dpkg/lock >/dev/null 2>&1; do sleep 3; done'",
            timeout=timeout + 10,
        )

    def _configure_github_access(self) -> None:
        """On IPv6-only VPS, add /etc/hosts overrides for the GitHub IPv6 proxy."""
        if ':' not in (self.host or ''):
            return
        logger.info("IPv6-only VPS: configuring GitHub IPv6 proxy via /etc/hosts...")
        self.run_command(
            "grep -q 'github-ipv6-proxy' /etc/hosts || "
            "printf '\\n# GitHub IPv6 proxy (danwin1210.de)\\n"
            "2a01:4f8:c010:d56::2 github.com\\n"
            "2a01:4f8:c010:d56::3 api.github.com\\n"
            "2a01:4f8:c010:d56::4 codeload.github.com\\n"
            "2a01:4f8:c010:d56::6 ghcr.io\\n"
            "2a01:4f8:c010:d56::8 uploads.github.com\\n"
            "2606:50c0:8000::133 objects.githubusercontent.com\\n"
            "' >> /etc/hosts"
        )

    def install_dependencies(self) -> None:
        """Install system dependencies (Python3, pip, git, libsodium-dev, deno)."""
        logger.info("Installing system dependencies...")

        self._configure_github_access()

        self._wait_for_apt_lock()
        self.run_command("apt-get update -y", timeout=120)

        packages = [
            "python3",
            "python3-pip",
            "python3-venv",
            "git",
            "libsodium-dev",
            "build-essential",
            "ffmpeg",
            "unzip",
        ]

        self.run_command(
            f"apt-get install -y {' '.join(packages)}",
            timeout=300
        )

        _, _, deno_check = self.run_command("which deno", check=False)
        if deno_check != 0:
            logger.info("Installing deno...")
            self.run_command(
                "curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh",
                timeout=120
            )

        logger.info("System dependencies installed")

    def setup_firewall(self, extra_ports: Optional[list] = None) -> None:
        """Configure UFW firewall: SSH, BitTorrent ports, IPv8, plus any extra_ports."""
        logger.info("Configuring firewall...")
        self.run_command("apt-get install -y ufw", timeout=60)
        self.run_command("ufw --force reset", check=False)
        self.run_command("ufw default deny incoming")
        self.run_command("ufw default allow outgoing")
        self.run_command("ufw allow 22/tcp comment 'SSH'")
        self.run_command("ufw allow 6881:6889/udp comment 'BitTorrent DHT'")
        self.run_command("ufw allow 6881:6999/tcp comment 'BitTorrent'")
        self.run_command("ufw allow 8090/udp comment 'IPv8'")

        if extra_ports:
            for port in extra_ports:
                self.run_command(f"ufw allow {port}")
                logger.info("Allowed extra port: %s", port)

        self.run_command("ufw --force enable")
        stdout, _, _ = self.run_command("ufw status verbose", check=False)
        logger.info("Firewall status:\n%s", stdout)

        logger.info("Firewall configured successfully")

    def deploy_mycelium(
        self,
        repo_url: Optional[str] = None,
        branch: str = "main",
        subpath: Optional[str] = None
    ) -> None:
        """Clone repo with sparse checkout into REMOTE_BASE_DIR, or pull if it exists."""
        repo_url = repo_url or self.MYCELIUM_REPO_URL
        subpath = subpath or self.MYCELIUM_SUBPATH

        logger.info("Deploying mycelium from %s (subpath: %s)", repo_url, subpath)

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

    def deploy_video_ids(self, local_path: str) -> None:
        """Upload video IDs file to remote server."""
        if not Path(local_path).exists():
            raise DeployerError(f"Video IDs file not found: {local_path}")

        logger.info("Uploading video IDs file: %s -> %s", local_path, self.REMOTE_VIDEO_IDS_FILE)
        self.upload_file(local_path, self.REMOTE_VIDEO_IDS_FILE)
        logger.info("Video IDs file deployed successfully")

    def deploy_cookies(self, local_path: str) -> None:
        """Upload YouTube cookies file to remote server."""
        if not Path(local_path).exists():
            raise DeployerError(f"Cookies file not found: {local_path}")

        logger.info("Uploading cookies file: %s -> %s", local_path, self.REMOTE_COOKIES_FILE)
        self.upload_file(local_path, self.REMOTE_COOKIES_FILE)
        logger.info("Cookies file deployed successfully")

    def set_environment_variable(self, name: str, value: str) -> None:
        escaped_value = value.replace("'", "'\\''")
        self.run_command(
            f"sed -i '/^{name}=/d' /etc/environment && "
            f"echo \"{name}='{escaped_value}'\" >> /etc/environment"
        )

    def start_orchestrator(
        self,
        env: Optional[Dict[str, str]] = None,
        secrets: Optional[Dict[str, str]] = None,
    ) -> None:
        """Write secrets (mode 600), set env vars, and start the orchestrator wrapper."""
        logger.info("Starting orchestrator...")

        env_vars: Dict[str, str] = {
            "MYCELIUM_BASE_DIR": self.REMOTE_BASE_DIR,
            "MYCELIUM_VENV_DIR": self.REMOTE_VENV_DIR,
            "MYCELIUM_CONTENT_DIR": self.REMOTE_CONTENT_DIR,
            "MYCELIUM_LOG_DIR": self.REMOTE_LOG_DIR,
            "MYCELIUM_DATA_DIR": self.REMOTE_DATA_DIR,
            "MYCELIUM_VIDEO_IDS_FILE": self.REMOTE_VIDEO_IDS_FILE,
            "MYCELIUM_COOKIES_FILE": self.REMOTE_COOKIES_FILE,
        }
        if env:
            env_vars.update(env)

        if secrets:
            for remote_path, content in secrets.items():
                self._write_secret_file(content, remote_path)

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

        is_healthy = exit_code == 0 and bool(stdout.strip())

        if is_healthy:
            logger.info("Health check passed")
        else:
            logger.warning("Health check failed - orchestrator not running")

        return is_healthy


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

    logger.info("Generated SSH keypair: %s", key_path)
    return str(key_path), public_key
