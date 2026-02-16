from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict

from models.utils import parse_datetime


@dataclass
class Vote:
    """
    Represents a vote cast by a voter in an election.

    Attributes:
        id (str): Unique identifier for the vote.
        voter_id (str): Identifier of the voter who cast the vote.
        election_id (str): Identifier of the election in which the vote was cast.
        created_at (datetime): Timestamp when the vote was created (in UTC).
    """
    id: str
    voter_id: str
    election_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> Vote:
        """
        Creates a Vote instance from a dictionary.

        Args:
            data (Dict[str, Any]): A dictionary containing vote data.
        """
        if "created_at" in data:
            data["created_at"] = parse_datetime(data["created_at"])

        return Vote(**data)

    def to_dict(self) -> Dict[str, Any]:
        """
        Converts the Vote instance to a dictionary.

        :return: A dictionary representation of the Vote instance.
        """
        d = self.__dict__.copy()
        d["created_at"] = self.created_at.isoformat()
        return d