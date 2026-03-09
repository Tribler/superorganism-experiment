from dataclasses import dataclass

from ipv8.messaging.payload_dataclass import DataClassPayload

from messages.base_message import BaseMessage
from models.issue import Issue
from models.utils import parse_datetime


@dataclass
class IssueMessage(DataClassPayload[1], BaseMessage[Issue]):
    """
    Message to propagate issue data in JSON format.

    Attributes:
        id (str): Unique identifier for the issue.
        title (str): Title of the issue.
        description (str): Description of the issue.
        creator_id (str): Identifier of the creator of the issue.
        created_at (str): Timestamp when the issue was created (in ISO format).
        threshold (int): Vote threshold for the issue.
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
        return f"Issue(id={self.id}, title={self.title!r})"

    def to_model(self) -> Issue:
        return Issue(
            id=self.id,
            title=self.title,
            description=self.description,
            creator_id=self.creator_id,
            created_at=parse_datetime(self.created_at),
            threshold=self.threshold,
        )

    @classmethod
    def from_model(cls, issue: Issue) -> "IssueMessage":
        return cls(
            id=issue.id,
            title=issue.title,
            description=issue.description,
            creator_id=issue.creator_id,
            created_at=issue.created_at.isoformat(),
            threshold=issue.threshold,
        )

# Force schema generation once on import
_ = IssueMessage(id="", title="", description="", creator_id="", created_at="", threshold=0)