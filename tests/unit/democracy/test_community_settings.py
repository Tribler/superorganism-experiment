from __future__ import annotations

from typing import cast

import pytest

from ipv8.community import CommunitySettings

from democracy.network.community_settings import DemocracyCommunitySettings
from democracy.storage.repository import DemocracySyncRepository


# =========================================================
# from_base()
# =========================================================
def test_from_base_accepts_settings_with_repository_and_data_changed() -> None:
    repository = cast(DemocracySyncRepository, object())

    def data_changed() -> None:
        pass

    settings = CommunitySettings()
    settings.repository = repository
    settings.data_changed = data_changed
    settings.communication_interval = 60.0

    typed_settings = DemocracyCommunitySettings.from_base(settings)

    assert typed_settings is settings
    assert typed_settings.repository is repository
    assert typed_settings.data_changed is data_changed
    assert typed_settings.communication_interval == 60.0


def test_from_base_raises_when_repository_is_missing() -> None:
    settings = CommunitySettings()
    settings.data_changed = lambda: None
    settings.communication_interval = 60.0

    with pytest.raises(
        AttributeError,
        match="DemocracyCommunity requires 'repository' in community settings.",
    ):
        DemocracyCommunitySettings.from_base(settings)


def test_from_base_raises_when_data_changed_is_missing() -> None:
    settings = CommunitySettings()
    settings.repository = cast(DemocracySyncRepository, object())
    settings.communication_interval = 60.0

    with pytest.raises(
        AttributeError,
        match="DemocracyCommunity requires 'data_changed' in community settings.",
    ):
        DemocracyCommunitySettings.from_base(settings)


def test_from_base_raises_when_data_changed_is_not_callable() -> None:
    settings = CommunitySettings()
    settings.repository = cast(DemocracySyncRepository, object())
    settings.data_changed = "not callable"
    settings.communication_interval = 60.0

    with pytest.raises(
        TypeError,
        match="DemocracyCommunity setting 'data_changed' must be callable.",
    ):
        DemocracyCommunitySettings.from_base(settings)


def test_from_base_raises_when_communication_interval_is_missing() -> None:
    settings = CommunitySettings()
    settings.repository = cast(DemocracySyncRepository, object())
    settings.data_changed = lambda: None

    with pytest.raises(
        AttributeError,
        match=(
            "DemocracyCommunity requires 'communication_interval' in community "
            "settings."
        ),
    ):
        DemocracyCommunitySettings.from_base(settings)


def test_from_base_raises_when_communication_interval_is_not_numeric() -> None:
    settings = CommunitySettings()
    settings.repository = cast(DemocracySyncRepository, object())
    settings.data_changed = lambda: None
    settings.communication_interval = "fast"

    with pytest.raises(
        TypeError,
        match=(
            "DemocracyCommunity setting 'communication_interval' must be a real "
            "number."
        ),
    ):
        DemocracyCommunitySettings.from_base(settings)


# =========================================================
# initialize_args()
# =========================================================
def test_initialize_args_returns_expected_mapping() -> None:
    repository = cast(DemocracySyncRepository, object())

    def data_changed() -> None:
        pass

    initialize_args = DemocracyCommunitySettings.initialize_args(
        repository=repository,
        data_changed=data_changed,
        communication_interval=60.0,
    )

    assert initialize_args == {
        "repository": repository,
        "data_changed": data_changed,
        "communication_interval": 60.0,
    }
