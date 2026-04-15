import json
import time
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from healthchecker.db import (
    init_db, insert_sample, get_previous_samples,
    get_received_content_for_sampling, mark_content_checked
)
from healthchecker.client import DHTClient
from healthchecker.metrics import calculate_all_metrics

SAMPLE_INTERVAL_SECONDS = 30
RETRY_SLEEP_SECONDS = 60
MAX_RETRIES = 3


def now_unix() -> int:
    return int(datetime.now(timezone.utc).timestamp())


@dataclass
class TorrentEntry:
    url: str
    license: str
    magnet_link: Optional[str] = None

    @property
    def infohash(self) -> Optional[str]:
        if not self.magnet_link:
            return None
        try:
            parts = self.magnet_link.split("btih:")
            if len(parts) > 1:
                return parts[1].split("&")[0]
        except Exception:
            pass
        return None


class HealthChecker:

    def __init__(self):
        self.dht_client = DHTClient()

    def initialize(self):
        init_db()
        self.dht_client.bootstrap()
        entries = get_received_content_for_sampling(limit=1000)

    def get_next_entry(self) -> Optional[TorrentEntry]:
        entries = get_received_content_for_sampling(limit=10)
        if not entries:
            return None
        selected = random.choice(entries)
        return TorrentEntry(
            url=selected['url'],
            license=selected['license'],
            magnet_link=selected['magnet_link']
        )

    def check_torrent_health(self, entry: TorrentEntry) -> dict:
        infohash = entry.infohash

        if not infohash or not entry.magnet_link:
            return {
                "infohash": None,
                "peers": 0,
                "seeders": 0,
                "leechers": 0,
                "total_peers": 0,
                "status": "no_magnet",
                "entry": entry
            }

        detailed_stats = self.dht_client.get_detailed_stats(entry.magnet_link, timeout=10.0)

        seeders = detailed_stats.get("seeders", 0)
        leechers = detailed_stats.get("leechers", 0)
        total_peers = detailed_stats.get("total_peers", 0)

        previous_samples = get_previous_samples(infohash, limit=10)
        metrics = calculate_all_metrics(total_peers, previous_samples)

        return {
            "infohash": infohash,
            "peers": total_peers,
            "seeders": seeders,
            "leechers": leechers,
            "total_peers": total_peers,
            "growth": metrics["growth"],
            "shrink": metrics["shrink"],
            "exploding_estimator": metrics["exploding_estimator"],
            "peers_list": [],
            "status": "healthy" if total_peers > 0 else "no_peers",
            "entry": entry
        }

    def run_once(self):
        entry = self.get_next_entry()
        if not entry:
            return

        health = self.check_torrent_health(entry)

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

        if health["infohash"]:
            mark_content_checked(health["infohash"], ts)

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
