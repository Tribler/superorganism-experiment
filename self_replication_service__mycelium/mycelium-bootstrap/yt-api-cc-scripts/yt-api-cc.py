#!/usr/bin/env python3
"""Search YouTube for Creative Commons licensed videos."""

import sys

from utils import (
    get_youtube_client,
    load_existing_video_ids,
    save_video_ids,
    test_api_connection,
)

OUTPUT_FILE = "cc_urls.txt"
QUOTA_LIMIT = 10000

SEARCH_KEYWORDS = [
    "*",
    "No Copyright",
    "Creative Commons",
    "Copyright Free",
    "Royalty Free",
    "CC BY",
    "CC0",
    "Free Music",
    "NCS",
]


def search_cc_videos(youtube, keywords: list, existing_ids: set, quota_limit: int) -> set:
    """Search for CC-licensed videos using multiple keywords."""
    video_ids = existing_ids.copy()
    quota_used = 100  # From connection test

    print(f"\nStarting Creative Commons video collection...")
    print(f"Searching using {len(keywords)} different keywords\n")

    for keyword in keywords:
        if quota_used >= quota_limit:
            break

        print(f"Searching with keyword: '{keyword}'")
        next_page_token = None

        while quota_used < quota_limit:
            try:
                response = youtube.search().list(
                    part="id",
                    type="video",
                    videoLicense="creativeCommon",
                    maxResults=50,
                    pageToken=next_page_token,
                    q=keyword
                ).execute()

                quota_used += 100
                items = response.get("items", [])
                remaining = quota_limit - quota_used

                print(f"  Got {len(items)} results | Total unique: {len(video_ids)} | Quota: {remaining} remaining")

                for item in items:
                    video_id = item["id"]["videoId"]
                    video_ids.add(video_id)

                next_page_token = response.get("nextPageToken")
                if not next_page_token:
                    print(f"  Finished with '{keyword}'")
                    break

            except Exception as e:
                print(f"  Error: {e}")
                break

        print()

    print(f"Requests finished!")
    print(f"Unique videos: {len(video_ids)}")
    print(f"Quota used: {quota_used}")

    return video_ids


def main():
    youtube = get_youtube_client()

    if not test_api_connection(youtube, search_type="video"):
        print("\nExiting due to API connection failure...")
        sys.exit(1)

    existing_ids = load_existing_video_ids(OUTPUT_FILE)
    video_ids = search_cc_videos(youtube, SEARCH_KEYWORDS, existing_ids, QUOTA_LIMIT)
    save_video_ids(video_ids, OUTPUT_FILE)


if __name__ == "__main__":
    main()
