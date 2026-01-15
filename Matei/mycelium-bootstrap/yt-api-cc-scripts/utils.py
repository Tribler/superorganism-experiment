#!/usr/bin/env python3
"""Shared utilities for YouTube API Creative Commons scripts."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from googleapiclient.discovery import build


def get_youtube_client():
    """Initialize and return YouTube API client, or exit on failure."""
    load_dotenv(Path(__file__).parent.parent / ".ENV")
    api_key = os.getenv("YOUTUBE_API_KEY")

    if not api_key:
        print("Error: YOUTUBE_API_KEY not found in .ENV file")
        sys.exit(1)

    return build("youtube", "v3", developerKey=api_key)


def test_api_connection(youtube, search_type: str = "video") -> bool:
    """Test the YouTube API connection. Returns True if successful."""
    print("Testing YouTube API connection...")
    try:
        youtube.search().list(
            part="id",
            type=search_type,
            maxResults=1,
            q="test"
        ).execute()
        print("API key is valid and working!")
        return True
    except Exception as e:
        print(f"API connection failed: {e}")
        return False


def load_existing_video_ids(filepath: str) -> set:
    """Load existing video IDs from a URL file."""
    video_ids = set()
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            for line in f:
                line = line.strip()
                if "youtube.com/watch?v=" in line:
                    video_id = line.split("v=")[-1]
                    video_ids.add(video_id)
        print(f"Loaded {len(video_ids)} existing video IDs")
    return video_ids


def save_video_ids(video_ids: set, filepath: str) -> None:
    """Save video IDs as YouTube URLs to file."""
    with open(filepath, "w") as f:
        for video_id in sorted(video_ids):
            f.write(f"https://youtube.com/watch?v={video_id}\n")
    print(f"URLs saved to: {filepath}")
