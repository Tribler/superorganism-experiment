import csv
import random
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass


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
            # magnet:?xt=urn:btih:INFOHASH
            parts = self.magnet_link.split("btih:")
            if len(parts) > 1:
                infohash = parts[1].split("&")[0]
                return infohash
        except Exception:
            pass
        return None


class CSVTorrentLoader:
    
    def __init__(self, csv_path: str):
        self.csv_path = Path(csv_path)
        self.entries: List[TorrentEntry] = []
        
    def load(self) -> int:
        if not self.csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {self.csv_path}")
        
        with open(self.csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            # Expected columns
            required_cols = ['url', 'license', 'magnet_link']
            
            for row in reader:
                # Validate required columns
                if not all(col in row for col in required_cols):
                    continue
                
                entry = TorrentEntry(
                    url=row['url'].strip(),
                    license=row['license'].strip(),
                    magnet_link=row.get('magnet_link', '').strip() or None
                )
                
                self.entries.append(entry)
        
        return len(self.entries)
    
    def get_random_cc_entry(self) -> Optional[TorrentEntry]:
        if not self.entries:
            return None
        return random.choice(self.entries)
    
    def get_entry_by_infohash(self, infohash: str) -> Optional[TorrentEntry]:
        for entry in self.entries:
            if entry.infohash == infohash:
                return entry
        return None
    
    def update_magnet_link(self, url: str, magnet_link: str):
        for entry in self.entries:
            if entry.url == url:
                entry.magnet_link = magnet_link
                break