import hashlib
from typing import Final

# Community configuration constants
COMMUNITY_ID: Final[bytes] = hashlib.sha1(b"DemocracyCommunity").digest()

# Issue and vote management constants
ISSUE_TITLE_MIN_LENGTH: Final[int] = 10
ISSUE_TITLE_MAX_LENGTH: Final[int] = 100

ISSUE_DESCRIPTION_MIN_LENGTH: Final[int] = 100
ISSUE_DESCRIPTION_MAX_LENGTH: Final[int] = 5000

ISSUE_THRESHOLD: Final[int] = 9