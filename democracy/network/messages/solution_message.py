from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ipv8.messaging.payload_dataclass import DataClassPayload

from democracy.network.messages.base_message import BaseMessage
from democracy.models.solution import Solution
from democracy.models.utils import parse_datetime


@dataclass
class SolutionMessage(DataClassPayload[3], BaseMessage[Solution]):
    """
    Message to propagate solution data in JSON format.

    Attributes:
        id (str): Unique identifier for the solution.
        title (str): Title of the solution.
        description (str): Description of the solution.
        creator_id (str): Identifier of the creator of the solution.
        issue_id (str): Identifier of the issue of the solution.
        created_at (str): Timestamp when the solution was created (in ISO format).
    """
    title: str
    description: str
    creator_id: str
    issue_id: str
    id: str
    created_at: str

    @property
    def entity_id(self) -> UUID:
        return UUID(self.id)

    def brief(self) -> str:
        return f"Solution(id={self.id}, title={self.title!r})"

    def to_model(self) -> Solution:
        return Solution(
            title=self.title,
            description=self.description,
            creator_id=UUID(self.creator_id),
            issue_id=UUID(self.issue_id),
            id=UUID(self.id),
            created_at=parse_datetime(self.created_at),
        )

    @classmethod
    def from_model(cls, solution: Solution) -> SolutionMessage:
        return cls(
            title=solution.title,
            description=solution.description,
            creator_id=str(solution.creator_id),
            issue_id=str(solution.issue_id),
            id=str(solution.id),
            created_at=solution.created_at.isoformat(),
        )

# Force schema generation once on import
_ = SolutionMessage(title="", description="", creator_id="", issue_id="", id="", created_at="")