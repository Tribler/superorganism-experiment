import json
import time
import random
from datetime import datetime, timezone
from typing import Optional

from healthchecker.db import (
    init_db, insert_sample, get_previous_samples,
    get_received_content_for_sampling, mark_content_checked
)
from healthchecker.client import DHTClient
from healthchecker.csv_loader import CSVTorrentLoader, TorrentEntry
from healthchecker.metrics import calculate_all_metrics

SAMPLE_INTERVAL_SECONDS = 300
RETRY_SLEEP_SECONDS = 60
MAX_RETRIES = 3


def now_unix() -> int:
    return int(datetime.now(timezone.utc).timestamp())


class HealthChecker:

    def __init__(self, csv_path: Optional[str] = None, mode: str = "csv"):
        self.mode = mode  # "csv" or "ipv8"
        self.csv_path = csv_path
        self.csv_loader = None

        if mode == "csv":
            if not csv_path:
                raise ValueError("csv_path is required for csv mode")
            self.csv_loader = CSVTorrentLoader(csv_path)

        self.dht_client = DHTClient()

    def initialize(self):
        init_db()
        self.dht_client.bootstrap()

        if self.mode == "csv":
            print("Loading CSV file...")
            count = self.csv_loader.load()
            print(f"Loaded {count} total entries, {len(self.csv_loader.entries)} entries with magnet links")
        else:
            # IPV8 mode - check how many entries are in the database
            entries = get_received_content_for_sampling(limit=1000)
            print(f"IPV8 mode: {len(entries)} entries available from received content")

    def get_next_entry(self) -> Optional[TorrentEntry]:
        """Get the next entry to health-check based on mode."""
        if self.mode == "ipv8":
            entries = get_received_content_for_sampling(limit=10)
            if not entries:
                return None
            selected = random.choice(entries)
            return TorrentEntry(
                url=selected['url'],
                license=selected['license'],
                magnet_link=selected['magnet_link']
            )
        else:  # csv mode
            return self.csv_loader.get_random_cc_entry()
    
    def check_torrent_health(self, entry: TorrentEntry) -> dict:
        infohash = entry.infohash
        
        # If no magnet link or infohash, skip this entry
        if not infohash or not entry.magnet_link:
            print(f"No magnet link for {entry.url}, skipping...")
            return {
                "infohash": None,
                "peers": 0,
                "seeders": 0,
                "leechers": 0,
                "total_peers": 0,
                "status": "no_magnet",
                "entry": entry
            }
        
        dht_count, peers = 0, []
        
        # Get detailed stats (seeders, leechers) by connecting to the torrent
        detailed_stats = self.dht_client.get_detailed_stats(entry.magnet_link, timeout=10.0)
        
        seeders = detailed_stats.get("seeders", 0)
        leechers = detailed_stats.get("leechers", 0)
        total_peers = detailed_stats.get("total_peers", 0) or dht_count
        
        # Get previous samples to calculate growth/shrink/exploding
        previous_samples = get_previous_samples(infohash, limit=10)
        
        # Calculate metrics
        metrics = calculate_all_metrics(total_peers, seeders, leechers, previous_samples)
        
        return {
            "infohash": infohash,
            "peers": dht_count,
            "seeders": seeders,
            "leechers": leechers,
            "total_peers": total_peers,
            "growth": metrics["growth"],
            "shrink": metrics["shrink"],
            "exploding_estimator": metrics["exploding_estimator"],
            "peers_list": peers,
            "status": "healthy" if total_peers > 0 else "no_peers",
            "entry": entry
        }
    
    def run_once(self):
        # Get next entry based on mode
        entry = self.get_next_entry()
        if not entry:
            if self.mode == "ipv8":
                print("No entries available from IPV8 received content!")
            else:
                print("No entries available from CSV!")
            return

        print(f"\n[{datetime.now()}] Checking: {entry.url}")
        print(f"  License: {entry.license}")

        # Perform health check
        health = self.check_torrent_health(entry)

        # Record in database
        ts = now_unix()
        insert_sample(
            infohash_hex=health["infohash"] or "",
            ts=ts,
            peers_dht=health["peers"],
            raw_peers_json=json.dumps(health.get("peers_list", [])),
            url=entry.url,
            license=entry.license,
            magnet_link=entry.magnet_link or "",
            seeders=health.get("seeders", 0),
            leechers=health.get("leechers", 0),
            total_peers=health.get("total_peers", 0),
            growth=health.get("growth", 0.0),
            shrink=health.get("shrink", 0.0),
            exploding_estimator=health.get("exploding_estimator", 0.0)
        )

        # Mark content as checked if in IPV8 mode
        if self.mode == "ipv8" and health["infohash"]:
            mark_content_checked(health["infohash"], ts)

        print(f"  Result: {health.get('total_peers', 0)} total peers ({health.get('seeders', 0)} seeders, {health.get('leechers', 0)} leechers)")
        print(f"  Metrics: Growth={health.get('growth', 0.0):.2f}%, Shrink={health.get('shrink', 0.0):.2f}%, Exploding={health.get('exploding_estimator', 0.0):.2f}")

        return health
    
    def run_continuous(self):
        self.initialize()
        
        print(f"\nStarting continuous health checks (interval: {SAMPLE_INTERVAL_SECONDS}s)")
        print("Press Ctrl+C to stop\n")
        
        try:
            while True:
                self.run_once()
                time.sleep(SAMPLE_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            print("\n\nStopping health checker...")


def run(csv_path: Optional[str] = None, mode: str = "csv"):
    if mode == "csv" and not csv_path:
        csv_path = "torrents.csv"
    checker = HealthChecker(csv_path=csv_path, mode=mode)
    checker.run_continuous()
