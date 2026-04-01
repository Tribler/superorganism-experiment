from __future__ import annotations

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