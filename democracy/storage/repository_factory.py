from __future__ import annotations

from typing import Protocol

from democracy.storage.repository import DemocracyAppRepository, DemocracySyncRepository


class DemocracyRepositoryFactory(Protocol):
    """
    Factory for creating repository instances.

    Separate threads can request their own repository instance for the same storage
    backend and data location.
    """

    def create_app_repository(self) -> DemocracyAppRepository: ...

    def create_sync_repository(self) -> DemocracySyncRepository: ...
