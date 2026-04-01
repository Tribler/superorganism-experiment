from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ipv8.messaging.payload_dataclass import DataClassPayload

from democracy.network.messages.base_message import BaseMessage
from democracy.models.utils import parse_datetime
from democracy.models.issue_vote import IssueVote


@dataclass
class IssueVoteMessage(DataClassPayload[2], BaseMessage[IssueVote]):
    """
    Message to propagate issue vote data in JSON format.

    Attributes:
        voter_id (str): Identifier of the voter who cast the issue vote.
        issue_id (str): Identifier of the issue in which the vote was cast.
        id (str): Unique identifier for the issue vote.
        created_at (str): Timestamp when the vote was created (in ISO format).
    """
    voter_id: str
    issue_id: str
    id: str
    created_at: str

    @property
    def entity_id(self) -> UUID:
        return UUID(self.id)

    def brief(self) -> str:
        return f"Vote(id={self.id})"

    def to_model(self) -> IssueVote:
        return IssueVote(
            voter_id=UUID(self.voter_id),
            issue_id=UUID(self.issue_id),
            id=UUID(self.id),
            created_at=parse_datetime(self.created_at),
        )

    @classmethod
    def from_model(cls, vote: IssueVote) -> IssueVoteMessage:
        return cls(
            voter_id=str(vote.voter_id),
            issue_id=str(vote.issue_id),
            id=str(vote.id),
            created_at=vote.created_at.isoformat(),
        )

# Force schema generation once on import
_ = IssueVoteMessage(id="", voter_id="", issue_id="", created_at="")