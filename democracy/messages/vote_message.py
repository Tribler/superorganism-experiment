from dataclasses import dataclass

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
        election_id (str): Identifier of the election in which the vote was cast.
        created_at (str): Timestamp when the vote was created (in ISO format).
    """
    id: str
    voter_id: str
    election_id: str
    created_at: str

    @property
    def entity_id(self) -> str:
        return self.id

    def brief(self) -> str:
        return f"Vote(id={self.id})"

    def to_model(self) -> Vote:
        return Vote(
            id=self.id,
            voter_id=self.voter_id,
            election_id=self.election_id,
            created_at=parse_datetime(self.created_at),
        )

    @classmethod
    def from_model(cls, vote: Vote) -> "VoteMessage":
        return cls(
            id=vote.id,
            voter_id=vote.voter_id,
            election_id=vote.election_id,
            created_at=vote.created_at.isoformat(),
        )

# Force schema generation once on import
_ = VoteMessage(id="", voter_id="", election_id="", created_at="")