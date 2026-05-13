from __future__ import annotations

from numbers import Real
from typing import Callable, cast

from ipv8.community import CommunitySettings

from democracy.storage.repository import DemocracySyncRepository

DataChangedCallback = Callable[[], None]


class DemocracyCommunitySettings(CommunitySettings):
    """
    Typed view of the custom settings expected by DemocracyCommunity.

    IPv8 constructs a base CommunitySettings instance and populates the extra initialize
    values dynamically. This wrapper validates those fields once and then exposes them
    with concrete types inside the community implementation.
    """

    repository: DemocracySyncRepository
    data_changed: DataChangedCallback
    communication_interval: float

    @classmethod
    def from_base(cls, settings: CommunitySettings) -> "DemocracyCommunitySettings":
        """
        Validate and cast a base IPv8 community settings object.

        IPv8 provides custom initialization values dynamically, so this method checks that
        the required democracy-specific fields are present before the settings object is
        used by the community.

        :param settings: Base IPv8 community settings object.
        :return: The same settings object cast to DemocracyCommunitySettings.
        :raises AttributeError: If a required setting is missing.
        :raises TypeError: If data_changed is not callable.
        """
        repository = getattr(settings, "repository", None)
        if repository is None:
            msg = "DemocracyCommunity requires 'repository' in community settings."
            raise AttributeError(msg)

        data_changed = getattr(settings, "data_changed", None)
        if data_changed is None:
            msg = "DemocracyCommunity requires 'data_changed' in community settings."
            raise AttributeError(msg)
        if not callable(data_changed):
            msg = "DemocracyCommunity setting 'data_changed' must be callable."
            raise TypeError(msg)

        communication_interval = getattr(settings, "communication_interval", None)
        if communication_interval is None:
            msg = (
                "DemocracyCommunity requires 'communication_interval' in community "
                "settings."
            )
            raise AttributeError(msg)
        if not isinstance(communication_interval, Real):
            msg = (
                "DemocracyCommunity setting 'communication_interval' must be a real "
                "number."
            )
            raise TypeError(msg)

        return cast(DemocracyCommunitySettings, settings)

    @staticmethod
    def initialize_args(
        *,
        repository: DemocracySyncRepository,
        data_changed: DataChangedCallback,
        communication_interval: float,
    ) -> dict[str, object]:
        """
        Build the custom initialization arguments for DemocracyCommunity.

        The returned dictionary can be passed to IPv8 when creating the community so that
        the repository and data change callback are attached to its settings.

        :param repository: Repository used by the community to store and retrieve data.
        :param data_changed: Callback invoked when replicated democracy data changes.
        :param communication_interval: Interval in seconds between periodic inventory
                                       announcements.
        :return: Dictionary containing the custom community initialization arguments.
        """
        return {
            "repository": repository,
            "data_changed": data_changed,
            "communication_interval": communication_interval,
        }
