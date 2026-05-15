import hashlib
from typing import Final

# Community configuration constants
COMMUNITY_ID: Final[bytes] = hashlib.sha1(b"DemocracyCommunity").digest()

ISSUE_THRESHOLD: Final[int] = 9

FUNDING_PROTOCOL_LABEL: Final[bytes] =  b"superorganism-funding-v1"
