import time
import libtorrent as lt
from typing import Tuple, List, Dict


class DHTClient:
    def __init__(self, listen_port: int = 6881):
        self.ses = lt.session()
        self.ses.listen_on(listen_port, listen_port + 10)

        self.ses.add_dht_router("router.bittorrent.com", 6881)
        self.ses.add_dht_router("router.utorrent.com", 6881)
        self.ses.add_dht_router("router.bitcomet.com", 6881)
        self.ses.start_dht()
        
        self.torrents = {}
        # map torrent_handle to torrent_status
        self.torrent_handles = {}

    def bootstrap(self, wait_seconds: int = 10):
        start = time.time()
        while time.time() - start < wait_seconds:
            self._drain_alerts()
            time.sleep(0.5)

    def _drain_alerts(self):
        alerts = []
        while True:
            a = self.ses.pop_alerts()
            if not a:
                break
            alerts.append(a)
        return alerts
    
    def get_detailed_stats(self, magnet_link: str, timeout: float = 10.0) -> Dict:
        try:
            print(f"Getting detailed stats for magnet link: {magnet_link}")
            infohash_hex = self._extract_infohash(magnet_link)
            print(f"Extracted infohash: {infohash_hex}")
            if not infohash_hex:
                print(f"Invalid magnet link: {magnet_link}")
                return {"seeders": 0, "leechers": 0, "total_peers": 0, "error": "invalid_magnet"}
            
            print(f"DHT enabled: {self.ses.is_dht_running()}")
            print(f"DHT nodes: {self.ses.status().dht_nodes}")
            
            # Check if we already have this torrent
            if infohash_hex in self.torrents:
                print(f"Using existing torrent handle for: {infohash_hex}")
                h = self.torrents[infohash_hex]
            else:
                print(f"Adding new torrent: {infohash_hex}")
                # Add torrent to session (download metadata only)
                atp = lt.parse_magnet_uri(magnet_link)
                atp.save_path = '.'  # We don't actually download
                atp.storage_mode = lt.storage_mode_t.storage_mode_sparse
                atp.flags |= lt.torrent_flags.duplicate_is_error \
                            | lt.torrent_flags.upload_mode \
                            | lt.torrent_flags.duplicate_is_error
                
                try:
                    handle = self.ses.add_torrent(atp)
                    self.torrents[infohash_hex] = handle
                except Exception as e:
                    print(f"Error adding torrent: {e}")
                    return {"seeders": 0, "leechers": 0, "total_peers": 0, "error": str(e)}
            
            seeders = 0
            leechers = 0
            total_peers = 0
            # Wait for metadata and peer connections
            start = time.time()
            while time.time() - start < timeout:
                alerts = self.ses.pop_alerts()
                for a in alerts:
                    # add new torrents to our list of torrent_status
                    if isinstance(a, lt.add_torrent_alert):
                        print(f"Torrent added: {a.handle.name()}")
                        h = a.handle
                        # h.set_max_connections(60)
                        # h.set_max_uploads(-1)
                        self.torrent_handles[h] = h.status()

                    # update our torrent_status array for torrents that have
                    # changed some of their state
                    if isinstance(a, lt.state_update_alert):
                        for s in a.status:
                            # print(f"State Update: {s.name()}")
                            self.torrent_handles[s.handle] = s

                self.ses.post_torrent_updates()
                status = h.status()
                
                # Check if we have metadata
                if not status.has_metadata:
                    time.sleep(0.5)
                    continue
                
                # Get detailed stats
                print(f"Torrent status: {status}")
                seeders = status.list_seeds if hasattr(status, 'list_seeds') else 0
                leechers = status.list_peers - seeders if hasattr(status, 'list_peers') else 0
                total_peers = status.list_peers if hasattr(status, 'list_peers') else 0
                
                # If we have some data, return it
                if total_peers > 0 or time.time() - start > timeout - 2:
                    return {
                        "seeders": seeders,
                        "leechers": leechers,
                        "total_peers": total_peers,
                        "download_rate": status.download_rate if hasattr(status, 'download_rate') else 0,
                        "upload_rate": status.upload_rate if hasattr(status, 'upload_rate') else 0,
                        "progress": status.progress if hasattr(status, 'progress') else 0.0
                    }
                
                time.sleep(0.5)
            
            # Timeout - return what we have
            return {
                "seeders": seeders,
                "leechers": leechers,
                "total_peers": total_peers,
                "download_rate": 0,
                "upload_rate": 0,
                "progress": 0.0
            }
            
        except Exception as e:
            print(f"Error getting detailed stats: {e}")
            return {"seeders": 0, "leechers": 0, "total_peers": 0, "error": str(e)}
    
    def _extract_infohash(self, magnet_link: str) -> str:
        try:
            if "btih:" in magnet_link:
                parts = magnet_link.split("btih:")[1].split("&")[0]
                return parts
        except:
            pass
        return ""
