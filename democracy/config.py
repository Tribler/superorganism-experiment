import hashlib

from typing import Final

DATA_PATH: Final[str] = "data/"
COMMUNITY_ID: Final[bytes] = hashlib.sha1(b"ElectionCommunity").digest()
COMMUNICATION_INTERVAL: Final[float] = 60.0 # Seconds