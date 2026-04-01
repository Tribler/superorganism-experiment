from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ipv8.messaging.payload_dataclass import DataClassPayload

from democracy.network.messages.base_message import BaseMessage
from democracy.models.issue import Issue
from democracy.models.utils import parse_datetime


@dataclass
class IssueMessage(DataClassPayload[1], BaseMessage[Issue]):
    """
    Message to propagate issue data in JSON format.

    Attributes:
        title (str): Title of the issue.
        creator_id (str): Identifier of the creator of the issue.
        description (str): Description of the issue.
        id (str): Unique identifier for the issue.
        created_at (str): Timestamp when the issue was created (in ISO format).
    """
    title: str
    creator_id: str
    description: str
    id: str
    created_at: str

    @property
    def entity_id(self) -> UUID:
        return UUID(self.id)

    def brief(self) -> str:
        return f"Issue(id={self.id}, title={self.title!r})"

    def to_model(self) -> Issue:
        return Issue(
            title=self.title,
            creator_id=UUID(self.creator_id),
            description=self.description,
            id=UUID(self.id),
            created_at=parse_datetime(self.created_at),
        )

    @classmethod
    def from_model(cls, issue: Issue) -> IssueMessage:
        return cls(
            title=issue.title,
            creator_id=str(issue.creator_id),
            description=issue.description,
            id=str(issue.id),
            created_at=issue.created_at.isoformat(),
        )

# Force schema generation once on import
_ = IssueMessage(title="", creator_id="", description="", id="", created_at="")