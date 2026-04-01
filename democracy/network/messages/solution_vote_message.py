from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ipv8.messaging.payload_dataclass import DataClassPayload

from democracy.network.messages.base_message import BaseMessage
from democracy.models.utils import parse_datetime
from democracy.models.solution_vote import SolutionVote


@dataclass
class SolutionVoteMessage(DataClassPayload[4], BaseMessage[SolutionVote]):
    """
    Message to propagate solution vote data in JSON format.

    Attributes:
        id (str): Unique identifier for the solution vote.
        voter_id (str): Identifier of the voter who cast the solution vote.
        solution_id (str): Identifier of the solution in which the vote was cast.
        created_at (str): Timestamp when the vote was created (in ISO format).
    """
    voter_id: str
    solution_id: str
    id: str
    created_at: str

    @property
    def entity_id(self) -> UUID:
        return UUID(self.id)

    def brief(self) -> str:
        return f"Solution(id={self.id})"

    def to_model(self) -> SolutionVote:
        return SolutionVote(
            voter_id=UUID(self.voter_id),
            solution_id=UUID(self.solution_id),
            id=UUID(self.id),
            created_at=parse_datetime(self.created_at),
        )

    @classmethod
    def from_model(cls, vote: SolutionVote) -> SolutionVoteMessage:
        return cls(
            voter_id=str(vote.voter_id),
            solution_id=str(vote.solution_id),
            id=str(vote.id),
            created_at=vote.created_at.isoformat(),
        )

# Force schema generation once on import
_ = SolutionVoteMessage(id="", voter_id="", solution_id="", created_at="")