from dataclasses import dataclass
from uuid import UUID

from ipv8.messaging.payload_dataclass import DataClassPayload

from messages.base_message import BaseMessage
from models.utils import parse_datetime
from models.vote import Vote


@dataclass
class VoteMessage(DataClassPayload[2], BaseMessage[Vote]):
    """
    Message to propagate vote data in JSON format.

    Attributes:
        id (str): Unique identifier for the vote.
        voter_id (str): Identifier of the voter who cast the vote.
        issue_id (str): Identifier of the issue in which the vote was cast.
        created_at (str): Timestamp when the vote was created (in ISO format).
    """
    voter_id: str
    issue_id: str
    id: str
    created_at: str

    @property
    def entity_id(self) -> str:
        return self.id

    def brief(self) -> str:
        return f"Vote(id={self.id})"

    def to_model(self) -> Vote:
        return Vote(
            voter_id=UUID(self.voter_id),
            issue_id=UUID(self.issue_id),
            id=UUID(self.id),
            created_at=parse_datetime(self.created_at),
        )

    @classmethod
    def from_model(cls, vote: Vote) -> "VoteMessage":
        return cls(
            voter_id=str(vote.voter_id),
            issue_id=str(vote.issue_id),
            id=str(vote.id),
            created_at=vote.created_at.isoformat(),
        )

# Force schema generation once on import
_ = VoteMessage(id="", voter_id="", issue_id="", created_at="")