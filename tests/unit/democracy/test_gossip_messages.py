from __future__ import annotations

from math import ceil
from unittest.mock import patch
from uuid import UUID

import pytest

from democracy.network.messages import gossip_messages
from democracy.network.messages.gossip_messages import (
    GossipItem,
    IHaveMessage,
    MAX_GOSSIP_ITEMS_BLOB_BYTES,
    _canonicalize_items,
    _deduplicate_items,
    _encoded_size_for_item_count,
    batch_gossip_items,
    decode_gossip_items,
    encode_gossip_items,
    encoded_gossip_items_size,
    max_gossip_items_for_blob_size,
)
from democracy.network.object_type import ObjectType


# =========================================================
# _deduplicate_items()
# =========================================================
def test_deduplicate_items_removes_exact_duplicates_and_keeps_distinct_keys() -> None:
    shared_uuid = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    other_uuid = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    issue_item = GossipItem(object_type=ObjectType.ISSUE, object_uuid=shared_uuid)
    issue_vote_item = GossipItem(
        object_type=ObjectType.ISSUE_VOTE,
        object_uuid=shared_uuid,
    )
    solution_item = GossipItem(
        object_type=ObjectType.SOLUTION,
        object_uuid=other_uuid,
    )

    deduplicated_items = _deduplicate_items(
        [
            issue_item,
            issue_item,
            issue_vote_item,
            solution_item,
            solution_item,
        ]
    )

    assert deduplicated_items == [
        issue_item,
        issue_vote_item,
        solution_item,
    ]


# =========================================================
# _canonicalize_items()
# =========================================================
def test_canonicalize_items_deduplicates_and_sorts_by_type_then_uuid() -> None:
    first_issue_uuid = UUID("11111111-1111-4111-8111-111111111111")
    second_issue_uuid = UUID("22222222-2222-4222-8222-222222222222")
    vote_uuid = UUID("33333333-3333-4333-8333-333333333333")

    canonical_items = _canonicalize_items(
        [
            GossipItem(object_type=ObjectType.ISSUE_VOTE, object_uuid=vote_uuid),
            GossipItem(object_type=ObjectType.ISSUE, object_uuid=second_issue_uuid),
            GossipItem(object_type=ObjectType.ISSUE, object_uuid=first_issue_uuid),
            GossipItem(object_type=ObjectType.ISSUE, object_uuid=second_issue_uuid),
        ]
    )

    assert canonical_items == [
        GossipItem(object_type=ObjectType.ISSUE, object_uuid=first_issue_uuid),
        GossipItem(object_type=ObjectType.ISSUE, object_uuid=second_issue_uuid),
        GossipItem(object_type=ObjectType.ISSUE_VOTE, object_uuid=vote_uuid),
    ]


# =========================================================
# _encoded_size_for_item_count()
# =========================================================
def test_encoded_size_for_item_count_returns_expected_byte_sizes() -> None:
    assert _encoded_size_for_item_count(0) == 0
    assert _encoded_size_for_item_count(1) == ceil(130 / 8)
    assert _encoded_size_for_item_count(2) == ceil(2 * 130 / 8)


# =========================================================
# encoded_gossip_items_size()
# =========================================================
def test_encoded_gossip_items_size_uses_unique_item_count() -> None:
    duplicate_item = GossipItem(
        object_type=ObjectType.ISSUE,
        object_uuid=UUID("44444444-4444-4444-8444-444444444444"),
    )
    distinct_item = GossipItem(
        object_type=ObjectType.SOLUTION,
        object_uuid=UUID("55555555-5555-4555-8555-555555555555"),
    )

    assert encoded_gossip_items_size(
        [duplicate_item, duplicate_item, distinct_item]
    ) == ceil(2 * 130 / 8)


# =========================================================
# max_gossip_items_for_blob_size()
# =========================================================
def test_max_gossip_items_for_blob_size_returns_expected_capacity(monkeypatch) -> None:
    monkeypatch.setattr(gossip_messages, "MAX_GOSSIP_ITEMS_BLOB_BYTES", 1300)

    assert max_gossip_items_for_blob_size(0) == 0
    assert max_gossip_items_for_blob_size(16) == 0
    assert max_gossip_items_for_blob_size(17) == 1
    assert max_gossip_items_for_blob_size(MAX_GOSSIP_ITEMS_BLOB_BYTES) == 80


def test_max_gossip_items_for_blob_size_rejects_negative_sizes() -> None:
    with pytest.raises(
        ValueError,
        match="Maximum gossip blob size cannot be negative.",
    ):
        max_gossip_items_for_blob_size(-1)


# =========================================================
# batch_gossip_items()
# =========================================================
def test_batch_gossip_items_returns_no_batches_for_empty_items() -> None:
    assert list(batch_gossip_items([])) == []


def test_batch_gossip_items_rejects_too_small_blob_size(monkeypatch) -> None:
    item = GossipItem(
        object_type=ObjectType.ISSUE,
        object_uuid=UUID("44444444-4444-4444-8444-444444444444"),
    )
    monkeypatch.setattr(gossip_messages, "MAX_GOSSIP_ITEMS_BLOB_BYTES", 16)

    with pytest.raises(
        ValueError,
        match="Maximum gossip blob size is too small to fit one gossip item.",
    ):
        list(batch_gossip_items([item]))


def test_batch_gossip_items_deduplicates_once_and_batches_canonical_items(
    monkeypatch,
) -> None:
    items = [
        GossipItem(
            object_type=ObjectType.SOLUTION_VOTE,
            object_uuid=UUID("33333333-3333-4333-8333-333333333333"),
        ),
        GossipItem(
            object_type=ObjectType.ISSUE,
            object_uuid=UUID("22222222-2222-4222-8222-222222222222"),
        ),
        GossipItem(
            object_type=ObjectType.ISSUE,
            object_uuid=UUID("11111111-1111-4111-8111-111111111111"),
        ),
        GossipItem(
            object_type=ObjectType.SOLUTION_VOTE,
            object_uuid=UUID("33333333-3333-4333-8333-333333333333"),
        ),
    ]
    monkeypatch.setattr(gossip_messages, "MAX_GOSSIP_ITEMS_BLOB_BYTES", 34)

    batches = list(batch_gossip_items(items))

    assert batches == [
        [
            GossipItem(
                object_type=ObjectType.ISSUE,
                object_uuid=UUID("11111111-1111-4111-8111-111111111111"),
            ),
            GossipItem(
                object_type=ObjectType.ISSUE,
                object_uuid=UUID("22222222-2222-4222-8222-222222222222"),
            ),
        ],
        [
            GossipItem(
                object_type=ObjectType.SOLUTION_VOTE,
                object_uuid=UUID("33333333-3333-4333-8333-333333333333"),
            )
        ],
    ]


# =========================================================
# encode_gossip_items()
# =========================================================
def test_encode_gossip_items_returns_empty_bytes_for_empty_items() -> None:
    assert encode_gossip_items([]) == b""


def test_encode_gossip_items_encodes_expected_single_item_length() -> None:
    items = [
        GossipItem(
            object_type=ObjectType.ISSUE,
            object_uuid=UUID("12345678-1234-5678-1234-567812345678"),
        )
    ]

    encoded = encode_gossip_items(items)

    assert encoded == bytes.fromhex("0012345678123456781234567812345678")


def test_encode_gossip_items_encodes_canonicalized_items() -> None:
    first_id = UUID("11111111-1111-4111-8111-111111111111")
    second_id = UUID("22222222-2222-4222-8222-222222222222")
    expected_items = [
        GossipItem(object_type=ObjectType.ISSUE, object_uuid=first_id),
        GossipItem(object_type=ObjectType.SOLUTION_VOTE, object_uuid=second_id),
    ]

    encoded = encode_gossip_items(
        [
            expected_items[1],
            expected_items[0],
            expected_items[1],
        ]
    )

    assert encoded == bytes.fromhex(
        "004444444444450446044444444444444722222222222242228222222222222222"
    )


# =========================================================
# decode_gossip_items()
# =========================================================
def test_decode_gossip_items_logs_empty_payload() -> None:
    with patch("democracy.network.messages.gossip_messages.logger") as mock_logger:
        assert decode_gossip_items(b"") == []

    mock_logger.debug.assert_called_once_with("Received empty gossip items payload.")


def test_decode_gossip_items_rejects_invalid_payload_length() -> None:
    with patch("democracy.network.messages.gossip_messages.logger") as mock_logger:
        assert decode_gossip_items(b"\x00") == []

    mock_logger.debug.assert_called_once_with(
        "Received malformed gossip items payload: %d bytes is too short for one item.",
        1,
    )


def test_decode_gossip_items_logs_unknown_object_type_value() -> None:
    encoded = bytes.fromhex("0012345678123456781234567812345678")

    with (
        patch(
            "democracy.network.messages.gossip_messages.ObjectType"
        ) as mock_object_type,
        patch("democracy.network.messages.gossip_messages.logger") as mock_logger,
    ):
        mock_object_type.side_effect = ValueError("unknown object type")

        assert decode_gossip_items(encoded) == []

    mock_logger.debug.assert_called_once_with(
        "Received gossip item with unknown object type value: %d.",
        0,
    )


def test_binary_gossip_message_decodes_items() -> None:
    items = [
        GossipItem(
            object_type=ObjectType.ISSUE_VOTE,
            object_uuid=UUID("33333333-3333-4333-8333-333333333333"),
        )
    ]

    payload = IHaveMessage.from_items(items)

    assert payload.decode_items() == items


# =========================================================
# encode_gossip_items() / decode_gossip_items()
# =========================================================
def test_encode_and_decode_gossip_items_round_trip_single_item() -> None:
    items = [
        GossipItem(
            object_type=ObjectType.ISSUE,
            object_uuid=UUID("12345678-1234-5678-1234-567812345678"),
        )
    ]

    assert decode_gossip_items(encode_gossip_items(items)) == items


def test_encode_and_decode_gossip_items_round_trip_canonicalized_items() -> None:
    first_id = UUID("11111111-1111-4111-8111-111111111111")
    second_id = UUID("22222222-2222-4222-8222-222222222222")
    expected_items = [
        GossipItem(object_type=ObjectType.ISSUE, object_uuid=first_id),
        GossipItem(object_type=ObjectType.SOLUTION_VOTE, object_uuid=second_id),
    ]

    encoded = encode_gossip_items(
        [
            expected_items[1],
            expected_items[0],
            expected_items[1],
        ]
    )

    assert decode_gossip_items(encoded) == expected_items
