from __future__ import annotations

from pathlib import Path

from democracy.storage.repository import DemocracyAppRepository, DemocracySyncRepository
from democracy.storage.repository_factory import DemocracyRepositoryFactory
from democracy.storage.sqlite_repository import SQLiteDemocracyRepository


class SQLiteDemocracyRepositoryFactory(DemocracyRepositoryFactory):
    """
    Factory for SQLite-backed democracy repositories.
    """

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def create_app_repository(self) -> DemocracyAppRepository:
        return SQLiteDemocracyRepository(self._database_path)

    def create_sync_repository(self) -> DemocracySyncRepository:
        return SQLiteDemocracyRepository(self._database_path)
