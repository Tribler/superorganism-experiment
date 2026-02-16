from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict

from constants import ELECTION_THRESHOLD
from models.utils import parse_datetime


@dataclass
class Election:
    """
    Represents an election with its details.

    Attributes:
        id (str): Unique identifier for the election.
        title (str): Title of the election.
        description (str): Description of the election.
        creator_id (str): Identifier of the creator of the election.
        created_at (datetime): Timestamp when the election was created (in UTC).
        threshold (int): Vote threshold for the election.
    """
    id: str
    title: str
    description: str = ""
    creator_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    threshold: int = ELECTION_THRESHOLD

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Election":
        """
        Creates an Election instance from a dictionary.

        Args:
            data (Dict[str, Any]): A dictionary containing election data.
        """
        if "created_at" in data:
            data["created_at"] = parse_datetime(data["created_at"])

        return Election(**data)

    def to_dict(self) -> Dict[str, Any]:
        """
        Converts the Election instance to a dictionary.

        :return: A dictionary representation of the Election instance.
        """
        d = self.__dict__.copy()
        d["created_at"] = self.created_at.isoformat()
        return d