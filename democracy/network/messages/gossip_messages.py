from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from math import ceil
from typing import Iterable
from uuid import UUID

from ipv8.messaging.lazy_payload import VariablePayload, vp_compile

from democracy.network.object_type import ObjectType

logger = logging.getLogger(f"superorganism.{__name__}")

_OBJECT_TYPE_BITS = 2
_OBJECT_ID_BITS = 128
_BITS_PER_ITEM = _OBJECT_TYPE_BITS + _OBJECT_ID_BITS
MAX_GOSSIP_ITEMS_BLOB_BYTES = 1300


@dataclass(frozen=True)
class GossipItem:
    """
    Reference to a gossip object known by its type and UUID.

    :param object_type: Type of the object, for example "issue" or "solution_vote".
    :param object_uuid: UUID of the object.
    """

    object_type: ObjectType
    object_uuid: UUID


def _deduplicate_items(items: Iterable[GossipItem]) -> list[GossipItem]:
    """
    Remove duplicate gossip items based on their object type and object UUID.

    When multiple items refer to the same object, only one item is kept. If duplicates are
    present, the last item encountered for each object key is retained.

    :param items: Gossip items to deduplicate.
    :return: List of unique gossip items.
    """
    unique_items: dict[tuple[ObjectType, UUID], GossipItem] = {}
    for item in items:
        unique_items[(item.object_type, item.object_uuid)] = item
    return list(unique_items.values())


def _canonicalize_items(items: Iterable[GossipItem]) -> list[GossipItem]:
    """
    Remove duplicate gossip items and return them in a deterministic order.

    Items are considered duplicates when they refer to the same object type and object
    UUID. The returned list is sorted by object type and then by UUID.

    :param items: Gossip items to deduplicate and sort.
    :return: Canonical list of unique gossip items.
    """
    return sorted(
        _deduplicate_items(items),
        key=lambda gossip_item: (
            int(gossip_item.object_type),
            gossip_item.object_uuid.int,
        ),
    )


def _encoded_size_for_item_count(item_count: int) -> int:
    """
    Calculate the encoded byte size needed for a given number of gossip items.

    The size is based on the fixed number of bits required per item and is rounded up to a
    whole number of bytes.

    :param item_count: Number of gossip items to encode.
    :return: Number of bytes needed to encode the items.
    """
    return ceil(item_count * _BITS_PER_ITEM / 8)


def encoded_gossip_items_size(items: Iterable[GossipItem]) -> int:
    """
    Calculate the encoded byte size needed to store the given gossip items.

    Duplicate items are counted only once. The size is computed from the number of unique
    items and the fixed number of bits needed per item, rounded up to a whole number of
    bytes.

    :param items: Gossip items whose encoded size should be calculated.
    :return: Number of bytes needed to encode the unique gossip items.
    """
    item_count = len(_deduplicate_items(items))
    return _encoded_size_for_item_count(item_count)


def max_gossip_items_for_blob_size(max_blob_bytes: int) -> int:
    """
    Return the maximum number of fixed-width gossip items that fit in a blob.

    Gossip items currently use a fixed-width binary representation, so the maximum
    capacity depends only on the blob size and the number of bits per item.

    :param max_blob_bytes: Maximum encoded blob size in bytes.
    :return: Maximum number of gossip items that fit within the size limit.
    """
    if max_blob_bytes < 0:
        msg = "Maximum gossip blob size cannot be negative."
        raise ValueError(msg)

    return (max_blob_bytes * 8) // _BITS_PER_ITEM


def batch_gossip_items(items: Iterable[GossipItem]) -> Iterator[list[GossipItem]]:
    """
    Deduplicate, canonicalize, and batch gossip items for encoded transmission.

    Because gossip items are encoded with a fixed width, batching can be computed from the
    maximum number of canonical items that fit in one blob, without repeatedly measuring
    candidate batches.

    :param items: Gossip items to deduplicate, sort, and batch.
    :return: Iterator yielding canonical batches that each fit within the size limit.
    :raises ValueError: If the size limit is too small to fit even one gossip item.
    """
    canonical_items = _canonicalize_items(items)
    if not canonical_items:
        return

    max_items_per_batch = max_gossip_items_for_blob_size(MAX_GOSSIP_ITEMS_BLOB_BYTES)
    if max_items_per_batch < 1:
        msg = "Maximum gossip blob size is too small to fit one gossip item."
        raise ValueError(msg)

    for start_index in range(0, len(canonical_items), max_items_per_batch):
        yield canonical_items[start_index : start_index + max_items_per_batch]


def encode_gossip_items(items: Iterable[GossipItem]) -> bytes:
    """
    Encode gossip items into a compact deterministic byte representation.

    Duplicate items are removed before encoding, and the remaining items are sorted into
    canonical order. Each item is packed using its object type and object UUID, producing
    the same byte output for equivalent item sets.

    :param items: Gossip items to encode.
    :return: Encoded byte representation of the unique gossip items.
    """
    canonical_items = _canonicalize_items(items)
    item_count = len(canonical_items)
    if item_count == 0:
        return b""

    packed_items = 0
    for item in canonical_items:
        packed_items = (packed_items << _OBJECT_TYPE_BITS) | int(item.object_type)
        packed_items = (packed_items << _OBJECT_ID_BITS) | item.object_uuid.int

    return packed_items.to_bytes(
        _encoded_size_for_item_count(item_count),
        byteorder="big",
    )


def decode_gossip_items(items_blob: bytes) -> list[GossipItem]:
    """
    Decode compact gossip item bytes into gossip item references.

    The input is interpreted as a sequence of fixed-size packed items, where each item
    contains an object type and object UUID. Empty or malformed payloads return an empty
    list. Items with unknown object type values are skipped.

    :param items_blob: Encoded gossip item bytes to decode.
    :return: List of decoded gossip items.
    """
    payload_bytes = bytes(items_blob)
    if not payload_bytes:
        logger.debug("Received empty gossip items payload.")
        return []

    item_count = (len(payload_bytes) * 8) // _BITS_PER_ITEM
    if item_count == 0:
        logger.debug(
            "Received malformed gossip items payload: %d bytes is too short for one item.",
            len(payload_bytes),
        )
        return []

    expected_payload_bytes = _encoded_size_for_item_count(item_count)
    if len(payload_bytes) != expected_payload_bytes:
        logger.debug(
            "Received malformed gossip items payload: got %d bytes, expected %d bytes.",
            len(payload_bytes),
            expected_payload_bytes,
        )
        return []

    packed_items = int.from_bytes(payload_bytes, byteorder="big")
    decoded_items: list[GossipItem] = []

    for item_index in range(item_count):
        shift = (item_count - item_index - 1) * _BITS_PER_ITEM
        packed_item = (packed_items >> shift) & ((1 << _BITS_PER_ITEM) - 1)
        object_type_value = packed_item >> _OBJECT_ID_BITS
        object_uuid_value = packed_item & ((1 << _OBJECT_ID_BITS) - 1)

        try:
            object_type = ObjectType(object_type_value)
        except ValueError:
            logger.debug(
                "Received gossip item with unknown object type value: %d.",
                object_type_value,
            )
            continue

        decoded_items.append(
            GossipItem(
                object_type=object_type,
                object_uuid=UUID(int=object_uuid_value),
            )
        )

    return decoded_items


class _GossipItemsMessageBase(VariablePayload):
    """Shared payload behavior for gossip item messages."""

    format_list = ["varlenI"]
    names = ["items_blob"]
    _brief_name = "GOSSIP"

    @classmethod
    def from_items(
        cls,
        items: Iterable[GossipItem],
    ) -> "_GossipItemsMessageBase":
        """Create a gossip message from encoded gossip items."""
        return cls(encode_gossip_items(items))

    def decode_items(self) -> list[GossipItem]:
        """Decode the gossip items carried by this message."""
        return decode_gossip_items(self.items_blob)

    def brief(self) -> str:
        """Return a short human-readable description."""
        return f"{type(self)._brief_name}({len(self.items_blob)} bytes)"


@vp_compile
class IHaveMessage(_GossipItemsMessageBase):
    """
    Gossip inventory message.

    This message announces that the sender has one or more objects, without sending the
    full objects immediately.
    """

    msg_id = 5
    _brief_name = "IHAVE"


@vp_compile
class IWantMessage(_GossipItemsMessageBase):
    """
    Gossip request message.

    This message asks a peer to send the full objects for one or more object ids.
    """

    msg_id = 6
    _brief_name = "IWANT"
