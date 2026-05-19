from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict
from uuid import uuid4, UUID

from democracy.models.utils import parse_datetime


@dataclass(frozen=True)
class Solution:
    title: str
    description: str
    creator_id: UUID
    issue_id: UUID
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> Solution:
        if "id" in data:
            data["id"] = UUID(data["id"])

        if "creator_id" in data:
            data["creator_id"] = UUID(data["creator_id"])

        if "issue_id" in data:
            data["issue_id"] = UUID(data["issue_id"])

        if "created_at" in data:
            data["created_at"] = parse_datetime(data["created_at"])

        return Solution(**data)

    def to_dict(self) -> Dict[str, Any]:
        d = self.__dict__.copy()
        d["id"] = str(self.id)
        d["creator_id"] = str(self.creator_id)
        d["issue_id"] = str(self.issue_id)
        d["created_at"] = self.created_at.isoformat()
        return d

    def compute_hash(self) -> str:
        """
        Compute a deterministic content hash for this solution.

        The hash commits to all fields that define the solution object. The data is first
        converted to a canonical JSON representation with sorted keys and compact
        separators, so different peers compute the same hash for the same solution.

        :return: A SHA-256 content hash using the format sha256:<hex>.
        """
        payload = {
            "id": str(self.id),
            "issue_id": str(self.issue_id),
            "creator_id": str(self.creator_id),
            "title": self.title,
            "description": self.description,
            "created_at": self.created_at.isoformat(),
        }

        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        digest = hashlib.sha256(encoded).hexdigest()
        return digest