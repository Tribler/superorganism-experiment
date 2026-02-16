from dataclasses import dataclass

from ipv8.messaging.payload_dataclass import DataClassPayload

from messages.base_message import BaseMessage
from models.election import Election
from models.utils import parse_datetime


@dataclass
class ElectionMessage(DataClassPayload[1], BaseMessage[Election]):
    """
    Message to propagate election data in JSON format.

    Attributes:
        id (str): Unique identifier for the election.
        title (str): Title of the election.
        description (str): Description of the election.
        creator_id (str): Identifier of the creator of the election.
        created_at (str): Timestamp when the election was created (in ISO format).
        threshold (int): Vote threshold for the election.
    """
    id: str
    title: str
    description: str
    creator_id: str
    created_at: str
    threshold: int

    @property
    def entity_id(self) -> str:
        return self.id

    def brief(self) -> str:
        return f"Election(id={self.id}, title={self.title!r})"

    def to_model(self) -> Election:
        return Election(
            id=self.id,
            title=self.title,
            description=self.description,
            creator_id=self.creator_id,
            created_at=parse_datetime(self.created_at),
            threshold=self.threshold,
        )

    @classmethod
    def from_model(cls, election: Election) -> "ElectionMessage":
        return cls(
            id=election.id,
            title=election.title,
            description=election.description,
            creator_id=election.creator_id,
            created_at=election.created_at.isoformat(),
            threshold=election.threshold,
        )

# Force schema generation once on import
_ = ElectionMessage(id="", title="", description="", creator_id="", created_at="", threshold=0)