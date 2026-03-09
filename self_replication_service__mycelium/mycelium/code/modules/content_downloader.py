"""
Downloads CC vids YouTube until disk usage reaches threshold.
"""

import random
import re
import shutil
import subprocess
from pathlib import Path

from config import Config
from utils import setup_logger

logger = setup_logger(__name__, log_file=Config.LOG_DIR / "orchestrator.log")

VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")


class ContentDownloaderError(Exception):
    pass


class ContentDownloader:
    MAX_CONSECUTIVE_FAILURES = 10
    DOWNLOAD_TIMEOUT = 60  # 1 minute per video

    def __init__(self, video_ids_file: Path, content_dir: Path, disk_threshold: int = 50):
        self.video_ids_file = video_ids_file
        self.content_dir = content_dir
        self.disk_threshold = disk_threshold

        # Verify yt-dlp is available
        try:
            subprocess.run(
                ["yt-dlp", "--version"],
                capture_output=True, check=True, timeout=10
            )
        except FileNotFoundError:
            raise ContentDownloaderError("yt-dlp binary not found. Install with: pip install yt-dlp")
        except subprocess.CalledProcessError as e:
            raise ContentDownloaderError(f"yt-dlp check failed: {e}")

    def _get_disk_usage_percent(self) -> float:
        """Return disk usage percentage for content_dir's filesystem."""
        usage = shutil.disk_usage(self.content_dir)
        return (usage.used / usage.total) * 100

    def _get_already_downloaded_ids(self) -> set[str]:
        """Scan content_dir for already-downloaded video IDs (11-char prefix of filenames)."""
        downloaded = set()
        for f in self.content_dir.iterdir():
            if f.is_file() and not f.name.endswith(".info.json"):
                # Files are named: {video_id}_{title}.{ext}
                name = f.stem if not f.name.endswith(".info.json") else f.stem.rsplit(".", 1)[0]
                video_id = name.split("_", 1)[0]
                if VIDEO_ID_PATTERN.match(video_id):
                    downloaded.add(video_id)
        return downloaded

    def _download_video(self, video_id: str) -> bool:
        """Download a single video's audio via yt-dlp. Returns True on success."""
        url = f"https://www.youtube.com/watch?v={video_id}"
        output_template = str(self.content_dir / "%(id)s_%(title)s.%(ext)s")

        cmd = [
            "yt-dlp",
            "-f", "ba",
            "--extract-audio",
            "--audio-format", "flac",
            "--add-metadata",
            "--embed-thumbnail",
            "--write-info-json",
            "--no-overwrites",
            "-o", output_template,
            url,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.DOWNLOAD_TIMEOUT,
            )
            if result.returncode != 0:
                logger.warning(f"yt-dlp failed for {video_id}: {result.stderr[:200]}")
                return False
            logger.info(f"Downloaded {video_id}")
            return True
        except subprocess.TimeoutExpired:
            logger.warning(f"yt-dlp timed out for {video_id}")
            return False
        except Exception as e:
            logger.warning(f"Download error for {video_id}: {e}")
            return False

    def download_until_threshold(self) -> int:
        """Download vids until disk usage at a threshold. Returns count of downloads."""
        # shuffle video IDs
        try:
            text = self.video_ids_file.read_text()
        except FileNotFoundError:
            raise ContentDownloaderError(f"Video IDs file not found: {self.video_ids_file}")

        all_ids = [line.strip() for line in text.splitlines() if line.strip()]
        all_ids = [vid for vid in all_ids if VIDEO_ID_PATTERN.match(vid)]
        logger.info(f"Loaded {len(all_ids)} video IDs from {self.video_ids_file}")

        if not all_ids:
            logger.warning("No valid video IDs found")
            return 0

        random.shuffle(all_ids)

        # Skip already-downloaded
        already_downloaded = self._get_already_downloaded_ids()
        if already_downloaded:
            logger.info(f"Found {len(already_downloaded)} already-downloaded videos, skipping them")
        pending = [vid for vid in all_ids if vid not in already_downloaded]
        logger.info(f"{len(pending)} videos remaining to download")

        # Check if already at threshold
        current_usage = self._get_disk_usage_percent()
        if current_usage >= self.disk_threshold:
            logger.info(f"Disk already at {current_usage:.1f}% (threshold: {self.disk_threshold}%), skipping downloads")
            return 0

        downloaded = 0
        consecutive_failures = 0

        for video_id in pending:
            # Check disk threshold before each download
            current_usage = self._get_disk_usage_percent()
            if current_usage >= self.disk_threshold:
                logger.info(f"Disk at {current_usage:.1f}%, reached threshold of {self.disk_threshold}%")
                break

            if self._download_video(video_id):
                downloaded += 1
                consecutive_failures = 0
                if downloaded % 10 == 0:
                    logger.info(f"Progress: {downloaded} downloaded, disk at {self._get_disk_usage_percent():.1f}%")
            else:
                consecutive_failures += 1
                if consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                    logger.error(f"Stopping after {self.MAX_CONSECUTIVE_FAILURES} consecutive failures")
                    break

        logger.info(f"Content download complete: {downloaded} new files, disk at {self._get_disk_usage_percent():.1f}%")
        return downloaded
