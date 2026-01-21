"""
Git synchronization.

Checks repository for changes and automatically updates.
"""

import subprocess
from pathlib import Path
from typing import Optional
from utils import setup_logger

logger = setup_logger(__name__)


class CodeSyncError(Exception):
    pass


class GitOperationError(CodeSyncError):
    pass


class CodeSync:

    def __init__(self, repo_path: Path, remote: str = "origin", branch: str = "main"):

        self.repo_path = repo_path
        self.remote = remote
        self.branch = branch

        if not self._is_git_repository():
            raise GitOperationError(f"Not a git repository: {repo_path}")

    def _is_git_repository(self) -> bool:
        git_dir = self.repo_path / ".git"
        return git_dir.exists() and git_dir.is_dir()

    def _run_git_command(self, *args: str) -> str:

        try:
            result = subprocess.run(
                ["git", "-C", str(self.repo_path)] + list(args),
                capture_output=True,
                text=True,
                check=True,
                timeout=30
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            raise GitOperationError(f"Git command failed: {e.stderr}")
        except subprocess.TimeoutExpired:
            raise GitOperationError("Git command timed out")

    def get_local_hash(self) -> str:
        return self._run_git_command("rev-parse", "HEAD")

    def get_remote_hash(self) -> Optional[str]:
        try:
            remote_ref = f"{self.remote}/{self.branch}"
            output = self._run_git_command("ls-remote", self.remote, self.branch)

            if not output:
                logger.warning(f"Empty response from ls-remote for {remote_ref}")
                return None

            hash_value = output.split()[0]
            return hash_value
        except GitOperationError as e:
            logger.warning(f"Failed to query remote: {e}")
            return None

    def has_updates(self) -> bool:
        local_hash = self.get_local_hash()
        remote_hash = self.get_remote_hash()

        if remote_hash is None:
            return False

        return local_hash != remote_hash

    def pull_updates(self) -> bool:

        try:
            status = self._run_git_command("status", "--porcelain")
            if status:
                logger.info("Local changes detected, stashing before pull")
                self._run_git_command("stash", "push", "-m", "Auto-stash before update")

            logger.info(f"Pulling updates from {self.remote}/{self.branch}")
            self._run_git_command("pull", self.remote, self.branch)

            return True
        except GitOperationError as e:
            logger.error(f"Failed to pull updates: {e}")
            raise
