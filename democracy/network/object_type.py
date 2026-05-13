from __future__ import annotations

from enum import IntEnum


class ObjectType(IntEnum):
    """
    Supported democracy object types that can be exchanged through the gossip protocol.
    """

    ISSUE = 0
    ISSUE_VOTE = 1
    SOLUTION = 2
    SOLUTION_VOTE = 3
