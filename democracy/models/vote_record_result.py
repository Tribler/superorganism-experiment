from __future__ import annotations

from enum import Enum


class VoteRecordResult(Enum):
    CREATED = "created"
    ALREADY_VOTED = "already_voted"
