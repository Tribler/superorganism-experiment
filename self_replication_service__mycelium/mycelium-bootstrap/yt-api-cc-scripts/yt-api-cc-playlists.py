#!/usr/bin/env python3
"""Search YouTube playlists for Creative Commons licensed videos."""

import sys

from utils import (
    get_youtube_client,
    load_existing_video_ids,
    save_video_ids,
    test_api_connection,
)

OUTPUT_FILE = "cc_urls.txt"
QUOTA_LIMIT = 9500

PLAYLIST_KEYWORDS = [
    "Public Domain Playlist",
    "DMCA free playlist",
    "License Free Playlist",
    "free to use playlist",
    "Monetization Safe Playlist",
    "No Copyright Playlist",
]


def get_playlist_video_ids(youtube, playlist_id: str, quota_used: int, quota_limit: int) -> tuple[list, int]:
    """Extract all video IDs from a playlist. Returns (video_ids, updated_quota_used)."""
    video_ids = []
    next_page_token = None

    while quota_used < quota_limit:
        try:
            response = youtube.playlistItems().list(
                part="snippet",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=next_page_token
            ).execute()
            quota_used += 1

            for item in response.get("items", []):
                try:
                    video_id = item["snippet"]["resourceId"]["videoId"]
                    video_ids.append(video_id)
                except KeyError:
                    continue

            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break

        except Exception as e:
            print(f"    Error extracting videos: {e}")
            break

    return video_ids, quota_used


def filter_cc_videos(youtube, video_ids: list, quota_used: int, quota_limit: int) -> tuple[list, int]:
    """Filter video IDs to only those with CC license. Returns (cc_video_ids, updated_quota_used)."""
    cc_videos = []

    for i in range(0, len(video_ids), 50):
        if quota_used >= quota_limit:
            break

        batch = video_ids[i:i + 50]
        try:
            response = youtube.videos().list(
                part="status",
                id=",".join(batch)
            ).execute()
            quota_used += 1

            for video in response.get("items", []):
                try:
                    if video["status"]["license"] == "creativeCommon":
                        cc_videos.append(video["id"])
                except KeyError:
                    continue

        except Exception as e:
            print(f"    Error verifying licenses: {e}")
            continue

    return cc_videos, quota_used


def search_playlists_for_cc(youtube, keywords: list, existing_ids: set, quota_limit: int) -> set:
    """Search playlists for CC-licensed videos."""
    video_ids = existing_ids.copy()
    initial_count = len(video_ids)
    quota_used = 100  # From connection test
    playlists_processed = 0

    print(f"\nSearching playlists with {len(keywords)} keywords...\n")

    for keyword in keywords:
        if quota_used >= quota_limit:
            print("\nQuota limit reached")
            break

        print(f"Keyword: '{keyword}'")

        try:
            response = youtube.search().list(
                part="id",
                type="playlist",
                maxResults=50,
                q=keyword
            ).execute()
            quota_used += 100

            playlists = response.get("items", [])
            remaining = quota_limit - quota_used
            print(f"  Found {len(playlists)} playlists | Quota: {remaining} remaining")

            for playlist_item in playlists:
                if quota_used >= quota_limit:
                    break

                playlist_id = playlist_item["id"]["playlistId"]
                playlists_processed += 1

                playlist_video_ids, quota_used = get_playlist_video_ids(
                    youtube, playlist_id, quota_used, quota_limit
                )

                cc_videos, quota_used = filter_cc_videos(
                    youtube, playlist_video_ids, quota_used, quota_limit
                )

                new_cc_count = 0
                for vid in cc_videos:
                    if vid not in video_ids:
                        new_cc_count += 1
                    video_ids.add(vid)

                if new_cc_count > 0:
                    remaining = quota_limit - quota_used
                    print(f"  Playlist #{playlists_processed}: +{new_cc_count} CC videos | Total: {len(video_ids)} | Quota: {remaining}")

        except Exception as e:
            print(f"  Error: {e}")
            continue

        print()

    print(f"Initial videos: {initial_count}")
    print(f"New CC videos found: {len(video_ids) - initial_count}")
    print(f"Total unique CC videos: {len(video_ids)}")
    print(f"Efficiency: {len(video_ids) / quota_used:.2f} videos per quota unit")

    return video_ids


def main():
    youtube = get_youtube_client()

    if not test_api_connection(youtube, search_type="playlist"):
        print("\nExiting due to API connection failure...")
        sys.exit(1)

    print("\nLoading existing URLs from cc_urls.txt...")
    existing_ids = load_existing_video_ids(OUTPUT_FILE)

    video_ids = search_playlists_for_cc(youtube, PLAYLIST_KEYWORDS, existing_ids, QUOTA_LIMIT)

    print(f"Saving to {OUTPUT_FILE}...")
    save_video_ids(video_ids, OUTPUT_FILE)


if __name__ == "__main__":
    main()
