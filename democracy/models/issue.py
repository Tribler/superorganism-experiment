from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict

from constants import ISSUE_THRESHOLD
from models.utils import parse_datetime


@dataclass
class Issue:
    """
    Represents an issue with its details.

    Attributes:
        id (str): Unique identifier for the issue.
        title (str): Title of the issue.
        description (str): Description of the issue.
        creator_id (str): Identifier of the creator of the issue.
        created_at (datetime): Timestamp when the issue was created (in UTC).
        threshold (int): Vote threshold for the issue.
    """
    id: str
    title: str
    description: str = ""
    creator_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    threshold: int = ISSUE_THRESHOLD

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Issue":
        """
        Creates an Issue instance from a dictionary.

        Args:
            data (Dict[str, Any]): A dictionary containing issue data.
        """
        if "created_at" in data:
            data["created_at"] = parse_datetime(data["created_at"])

        return Issue(**data)

    def to_dict(self) -> Dict[str, Any]:
        """
        Converts the Issue instance to a dictionary.

        :return: A dictionary representation of the Issue instance.
        """
        d = self.__dict__.copy()
        d["created_at"] = self.created_at.isoformat()
        return d