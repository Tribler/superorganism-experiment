from __future__ import annotations

from uuid import uuid4

from democracy.models.issue import Issue
from democracy.network.community import DemocracyCommunity
from democracy.network.messages.gossip_messages import (
    GossipItem,
    IHaveMessage,
    IWantMessage,
)
from democracy.network.messages.issue_message import IssueMessage
from democracy.network.object_type import ObjectType


# =========================================================
# _brief()
# =========================================================
def test_brief_returns_item_count_for_ihave_message() -> None:
    payload = IHaveMessage.from_items(
        [
            GossipItem(
                object_type=ObjectType.ISSUE,
                object_uuid=uuid4(),
            )
        ]
    )

    assert DemocracyCommunity._brief(payload) == "IHAVE(1 item)"


def test_brief_returns_item_count_for_iwant_message() -> None:
    payload = IWantMessage.from_items(
        [
            GossipItem(
                object_type=ObjectType.SOLUTION,
                object_uuid=uuid4(),
            ),
            GossipItem(
                object_type=ObjectType.SOLUTION_VOTE,
                object_uuid=uuid4(),
            ),
        ]
    )

    assert DemocracyCommunity._brief(payload) == "IWANT(2 items)"


def test_brief_uses_base_message_brief_for_object_messages() -> None:
    issue = Issue(
        title="Issue title",
        description="Issue description",
        creator_id=uuid4(),
    )
    payload = IssueMessage.from_model(issue)

    assert DemocracyCommunity._brief(payload) == payload.brief()


def test_brief_falls_back_to_class_name_for_plain_objects() -> None:
    class PlainObject:
        pass

    assert DemocracyCommunity._brief(PlainObject()) == "PlainObject"
