import hashlib
from typing import Final

# Community configuration constants
COMMUNITY_ID: Final[bytes] = hashlib.sha1(b"DemocracyCommunity").digest()

ISSUE_THRESHOLD: Final[int] = 9