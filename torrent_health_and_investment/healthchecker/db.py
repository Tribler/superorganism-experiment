import sqlite3
from pathlib import Path
from typing import Optional, Set, List, Dict

DB_PATH = Path(__file__).parent.parent / "dht_health.db"

def get_con():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("PRAGMA journal_mode=WAL;")
    return con, cur

def init_db():
    (con, cur) = get_con()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dht_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            infohash TEXT NOT NULL,
            ts INTEGER NOT NULL,
            peers_dht INTEGER NOT NULL,
            raw_peers TEXT,
            url TEXT,
            license TEXT,
            magnet_link TEXT,
            seeders INTEGER DEFAULT 0,
            leechers INTEGER DEFAULT 0,
            total_peers INTEGER DEFAULT 0,
            growth REAL DEFAULT 0.0,
            shrink REAL DEFAULT 0.0,
            exploding_estimator REAL DEFAULT 0.0
        );
    """)
    
    # Indexes for faster queries
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_infohash ON dht_samples(infohash);
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_ts ON dht_samples(ts);
    """)

    # Table for content received via IPV8 network
    cur.execute("""
        CREATE TABLE IF NOT EXISTS received_content (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            infohash TEXT UNIQUE NOT NULL,
            url TEXT NOT NULL,
            license TEXT NOT NULL,
            magnet_link TEXT NOT NULL,
            received_at INTEGER NOT NULL,
            source_peer TEXT,
            last_checked INTEGER,
            check_count INTEGER DEFAULT 0
        );
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_received_infohash ON received_content(infohash);
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_last_checked ON received_content(last_checked);
    """)

    # Migration: add last_announced_at if absent
    try:
        cur.execute("ALTER TABLE received_content ADD COLUMN last_announced_at INTEGER")
        con.commit()
    except sqlite3.OperationalError:
        pass  # column already exists

    con.commit()
    con.close()


def insert_received_content(
    infohash: str,
    url: str,
    license: str,
    magnet_link: str,
    received_at: int,
    source_peer: str = None
) -> bool:
    """
    Insert received content from IPV8 network.
    Returns False if already exists (duplicate infohash).
    """
    (con, cur) = get_con()
    try:
        cur.execute("""
            INSERT INTO received_content
                (infohash, url, license, magnet_link, received_at, source_peer, last_announced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(infohash) DO UPDATE SET
                last_announced_at = excluded.last_announced_at
        """, (infohash, url, license, magnet_link, received_at, source_peer, received_at))
        con.commit()
        return True
    finally:
        con.close()


def get_received_content_for_sampling(limit: int = 10) -> List[Dict]:
    """
    Get received content entries for health checking.
    Prioritizes entries that haven't been checked yet.
    """
    (con, cur) = get_con()
    cur.execute("""
        SELECT infohash, url, license, magnet_link
        FROM received_content
        ORDER BY last_checked ASC NULLS FIRST, received_at DESC
        LIMIT ?
    """, (limit,))
    results = cur.fetchall()
    con.close()

    return [
        {
            'infohash': r[0],
            'url': r[1],
            'license': r[2],
            'magnet_link': r[3]
        }
        for r in results
    ]


def mark_content_checked(infohash: str, checked_at: int) -> None:
    """Mark content as checked and increment check count."""
    (con, cur) = get_con()
    cur.execute(
        """UPDATE received_content
           SET last_checked = ?, check_count = check_count + 1
           WHERE infohash = ?""",
        (checked_at, infohash)
    )
    con.commit()
    con.close()


def get_all_received_infohashes() -> Set[str]:
    """Get all infohashes from received content for deduplication on startup."""
    (con, cur) = get_con()
    cur.execute("SELECT infohash FROM received_content")
    results = cur.fetchall()
    con.close()
    return {r[0] for r in results}


def purge_stale_entries(cutoff_ts: int, keep_samples: int = 30) -> int:
    """
    Remove received_content rows not re-announced since cutoff_ts,
    their dht_samples, and trim remaining samples to keep_samples per infohash.
    Returns number of content rows deleted.
    """
    con, cur = get_con()

    cur.execute("""
        SELECT infohash FROM received_content
        WHERE COALESCE(last_announced_at, received_at) < ?
    """, (cutoff_ts,))
    stale = [r[0] for r in cur.fetchall()]

    if stale:
        placeholders = ",".join("?" * len(stale))
        cur.execute(f"DELETE FROM dht_samples WHERE infohash IN ({placeholders})", stale)
        cur.execute(f"DELETE FROM received_content WHERE infohash IN ({placeholders})", stale)

    # Trim dht_samples: keep last keep_samples rows per infohash
    cur.execute("""
        DELETE FROM dht_samples
        WHERE id NOT IN (
            SELECT id FROM dht_samples d
            WHERE (
                SELECT COUNT(*) FROM dht_samples d2
                WHERE d2.infohash = d.infohash AND d2.ts >= d.ts
            ) <= ?
        )
    """, (keep_samples,))

    con.commit()
    con.close()
    return len(stale)


def insert_sample(
    infohash_hex: str, 
    ts: int, 
    peers_dht: int, 
    raw_peers_json: Optional[str] = None,
    url: Optional[str] = None,
    license: Optional[str] = None,
    magnet_link: str | None = None,
    seeders: int = 0,
    leechers: int = 0,
    total_peers: int = 0,
    growth: float = 0.0,
    shrink: float = 0.0,
    exploding_estimator: float = 0.0
):
    (con, cur) = get_con()
    cur.execute(
        """INSERT INTO dht_samples
           (infohash, ts, peers_dht, raw_peers, url, license, magnet_link,
            seeders, leechers, total_peers, growth, shrink, exploding_estimator) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (infohash_hex, ts, peers_dht, raw_peers_json, url, license, magnet_link,
         seeders, leechers, total_peers, growth, shrink, exploding_estimator),
    )
    con.commit()
    con.close()

def get_all_torrents_with_health(limit: int = 500) -> list:
    con, cur = get_con()
    cur.execute("""
        SELECT rc.infohash, s.ts, rc.url, rc.license, rc.magnet_link,
               COALESCE(s.seeders, 0), COALESCE(s.leechers, 0), COALESCE(s.total_peers, 0),
               COALESCE(s.growth, 0.0), COALESCE(s.shrink, 0.0), COALESCE(s.exploding_estimator, 0.0)
        FROM received_content rc
        LEFT JOIN (
            SELECT infohash, MAX(ts) AS max_ts
            FROM dht_samples
            GROUP BY infohash
        ) latest ON rc.infohash = latest.infohash
        LEFT JOIN dht_samples s
               ON s.infohash = rc.infohash AND s.ts = latest.max_ts
        ORDER BY s.ts DESC NULLS LAST, rc.received_at DESC
        LIMIT ?
    """, (limit,))
    results = cur.fetchall()
    con.close()
    return [
        {
            "infohash": r[0] or "",
            "timestamp": r[1],           # None → widget will show "-"
            "url": r[2] or "",
            "license": r[3] or "",
            "magnet_link": r[4] or "",
            "seeders": r[5],
            "leechers": r[6],
            "total_peers": r[7],
            "growth": float(r[8]),
            "shrink": float(r[9]),
            "exploding_estimator": float(r[10]),
        }
        for r in results
    ]


def get_previous_samples(infohash: str, limit: int = 5) -> list:
    (con, cur) = get_con()
    cur.execute("""
        SELECT ts, total_peers, seeders, leechers
        FROM dht_samples
        WHERE infohash = ?
        ORDER BY ts DESC
        LIMIT ?
    """, (infohash, limit))
    results = cur.fetchall()
    con.close()
    
    return [
        {
            "timestamp": r[0] or 0,
            "total_peers": r[1] if r[1] is not None else 0,
            "seeders": r[2] if r[2] is not None else 0,
            "leechers": r[3] if r[3] is not None else 0
        }
        for r in results
    ]

def get_latest_seeding_levels(limit: int = 100) -> list:
    (con, cur) = get_con()
    # Get the most recent sample for each infohash
    cur.execute("""
        SELECT s1.infohash, s1.ts, s1.peers_dht, s1.url, 
               s1.license, s1.magnet_link, s1.seeders, s1.leechers, s1.total_peers, 
               s1.growth, s1.shrink, s1.exploding_estimator
        FROM dht_samples s1
        INNER JOIN (
            SELECT infohash, MAX(ts) as max_ts
            FROM dht_samples
            GROUP BY infohash
        ) s2 ON s1.infohash = s2.infohash AND s1.ts = s2.max_ts
        ORDER BY s1.ts DESC
        LIMIT ?
    """, (limit,))
    results = cur.fetchall()
    con.close()
    
    return [
        {
            "infohash": r[0] or "",
            "timestamp": r[1] or 0,
            "peers": r[2] or 0,
            "url": r[3] or "",
            "license": r[4] or "",
            "magnet_link": r[5] or "",
            "seeders": r[6] if r[6] is not None else 0,
            "leechers": r[7] if r[7] is not None else 0,
            "total_peers": r[8] if r[8] is not None else 0,
            "growth": float(r[9]) if r[9] is not None else 0.0,
            "shrink": float(r[10]) if r[10] is not None else 0.0,
            "exploding_estimator": float(r[11]) if r[11] is not None else 0.0
        }
        for r in results
    ]
