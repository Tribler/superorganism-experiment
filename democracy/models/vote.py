from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict
from uuid import uuid4, UUID

from models.utils import parse_datetime


@dataclass
class Vote:
    """
    Represents a vote cast by a voter on an issue.

    Attributes:
        id (str): Unique identifier for the vote.
        voter_id (str): Identifier of the voter who cast the vote.
        issue_id (str): Identifier of the issue in which the vote was cast.
        created_at (datetime): Timestamp when the vote was created (in UTC).
    """
    voter_id: UUID
    issue_id: UUID
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> Vote:
        """
        Creates a Vote instance from a dictionary.

        Args:
            data (Dict[str, Any]): A dictionary containing vote data.
        """
        if "id" in data:
            data["id"] = UUID(data["id"])

        if "voter_id" in data:
            data["voter_id"] = UUID(data["voter_id"])

        if "issue_id" in data:
            data["issue_id"] = UUID(data["issue_id"])

        if "created_at" in data:
            data["created_at"] = parse_datetime(data["created_at"])

        return Vote(**data)

    def to_dict(self) -> Dict[str, Any]:
        """
        Converts the Vote instance to a dictionary.

        :return: A dictionary representation of the Vote instance.
        """
        d = self.__dict__.copy()
        d["id"] = str(self.id)
        d["voter_id"] = str(self.voter_id)
        d["issue_id"] = str(self.issue_id)
        d["created_at"] = self.created_at.isoformat()
        return d