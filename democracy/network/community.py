from __future__ import annotations

import logging

from typing import Any, Iterable, Optional, Protocol, Set, runtime_checkable

from ipv8.community import Community, CommunitySettings
from ipv8.lazy_community import lazy_wrapper
from ipv8.messaging.serialization import Payload
from ipv8.peer import Peer

from democracy.constants import COMMUNITY_ID
from democracy.network.community_settings import (
    DataChangedCallback,
    DemocracyCommunitySettings,
)
from democracy.network.messages.base_message import BaseMessage
from democracy.network.messages.gossip_messages import (
    GossipItem,
    IHaveMessage,
    IWantMessage,
    batch_gossip_items,
)
from democracy.network.object_type import ObjectType
from democracy.network.replication import (
    ReplicationHandler,
    StoreStatus,
    build_replication_handlers,
)

logger = logging.getLogger(f"superorganism.{__name__}")


@runtime_checkable
class HasBrief(Protocol):
    def brief(self) -> str: ...


class DemocracyCommunity(Community):
    """
    Community to disseminate democracy objects using push/pull gossip.

    Peers announce inventory with IHAVE, request unknown objects with IWANT,
    and exchange the full object only when it is needed locally.
    """

    community_id = COMMUNITY_ID

    def __init__(self, settings: CommunitySettings) -> None:
        """
        Initialize the democracy community and register all gossip message handlers.

        The provided IPv8 settings are validated and cast to the democracy-specific
        settings type. The community then builds the replication handlers for all
        supported object types and registers handlers for IHAVE, IWANT, and concrete
        object messages.

        :param settings: IPv8 community settings containing the repository and data change
                         callback.
        :raises ValueError: If multiple replication handlers are registered for the same
                            object type.
        """
        typed_settings = DemocracyCommunitySettings.from_base(settings)
        super().__init__(typed_settings)

        self.repository = typed_settings.repository
        self.data_changed: DataChangedCallback = typed_settings.data_changed
        self._communication_interval = typed_settings.communication_interval

        replication_handlers = tuple(build_replication_handlers(self.repository))
        handlers_by_type: dict[ObjectType, ReplicationHandler[Any]] = {}
        handlers_by_model_cls: dict[type[Any], ReplicationHandler[Any]] = {}
        for handler in replication_handlers:
            if handler.object_type in handlers_by_type:
                msg = (
                    "Duplicate replication handler registered for object type "
                    f"{handler.object_type}."
                )
                raise ValueError(msg)
            if handler.model_cls in handlers_by_model_cls:
                msg = (
                    "Duplicate replication handler registered for model class "
                    f"{handler.model_cls!r}."
                )
                raise ValueError(msg)
            handlers_by_type[handler.object_type] = handler
            handlers_by_model_cls[handler.model_cls] = handler

        self._replication_handlers = replication_handlers
        self._handlers_by_type = handlers_by_type
        self._handlers_by_model_cls = handlers_by_model_cls

        self.add_message_handler(IHaveMessage, self.on_ihave_message)
        self.add_message_handler(IWantMessage, self.on_iwant_message)

        for handler in self._replication_handlers:
            self._register_object_message_handler(handler)

    def _register_object_message_handler(
        self,
        handler: ReplicationHandler[Any],
    ) -> None:
        """
        Register the incoming message handler for one replicated object type.

        The generated handler wraps the object-specific message class and forwards
        received objects to the shared object handling logic, together with the
        corresponding object type.

        :param handler: Replication handler describing the object type and message class
                        to register.
        :return: None
        """

        @lazy_wrapper(handler.message_cls)
        def on_message(
            inner_self: "DemocracyCommunity",
            peer: Peer,
            payload: BaseMessage[Any],
        ) -> None:
            inner_self._handle_object_message(peer, payload, handler.object_type)

        self.add_message_handler(
            handler.message_cls, on_message.__get__(self, type(self))
        )

    def on_start(self) -> None:
        """
        Start the periodic inventory announcement task.

        The task periodically announces all locally known object identifiers using IHAVE
        messages. Full objects are not sent during this step; peers request missing
        objects separately with IWANT.

        :return: None
        """
        self.register_task(
            "announce_inventory",
            self._announce_full_inventory,
            interval=self._communication_interval,
            delay=0,
        )

    async def _announce_full_inventory(self) -> None:
        """
        Announce all locally known object identifiers to connected peers.

        This method is used by the periodic communication task. It builds the current
        local inventory and sends it as IHAVE messages, allowing peers to request any
        missing objects with IWANT.

        :return: None
        """
        self._announce_inventory(self._get_local_inventory())

    @staticmethod
    def _brief(payload: object) -> str:
        """
        Return a short human-readable description of a message payload.

        Gossip messages are summarized by their message type and number of contained
        items, while regular object messages use their own brief representation.

        :param payload: Message payload to describe.
        :return: Short description suitable for logging.
        """
        if isinstance(payload, IHaveMessage):
            item_count = len(payload.decode_items())
            item_label = "item" if item_count == 1 else "items"
            return f"IHAVE({item_count} {item_label})"
        if isinstance(payload, IWantMessage):
            item_count = len(payload.decode_items())
            item_label = "item" if item_count == 1 else "items"
            return f"IWANT({item_count} {item_label})"
        if isinstance(payload, HasBrief):
            return payload.brief()
        return payload.__class__.__name__

    def _multicast(
        self,
        payload: Payload,
        skip_peers: Optional[Set[Peer]] = None,
    ) -> None:
        """
        Send a payload to all connected peers, except the peers that should be skipped.

        :param payload: Message payload to send.
        :param skip_peers: Optional set of peers that should not receive the payload.
        :return: None
        """
        if skip_peers is None:
            skip_peers = set()

        for peer in self.get_peers():
            if peer in skip_peers:
                continue

            self._send_to_peer(peer, payload)

    def _send_to_peer(self, peer: Peer, payload: Payload) -> None:
        """
        Send a payload to a single peer.

        The message is logged before it is sent through IPv8.

        :param peer: Peer that should receive the payload.
        :param payload: Message payload to send.
        :return: None
        """
        logger.debug(f"{self.my_peer}: Sending {self._brief(payload)} to peer {peer}.")
        self.ez_send(peer, payload)

    def _get_local_inventory(self) -> list[GossipItem]:
        """
        Build an inventory of all democracy objects stored locally.

        Each replicated model is converted into a gossip item containing its object type
        and identifier. The resulting inventory can be announced to peers using IHAVE
        messages.

        :return: Gossip items for all locally known replicated objects.
        """
        return [
            handler.build_item(model)
            for handler in self._replication_handlers
            for model in handler.get_all_models()
        ]

    def _announce_inventory(
        self,
        items: Iterable[GossipItem],
        skip_peers: Optional[Set[Peer]] = None,
    ) -> None:
        """
        Announce known object identifiers to connected peers using IHAVE messages.

        The inventory is split into batches before sending, so large local stores do not
        produce oversized gossip messages.

        :param items: Gossip items representing locally known objects.
        :param skip_peers: Optional set of peers that should not receive the announcement.
        :return: None
        """
        for batch in batch_gossip_items(items):
            self._multicast(
                IHaveMessage.from_items(batch),
                skip_peers=skip_peers,
            )

    def broadcast_created_model(
        self,
        model: Any,
        skip_peers: Optional[Set[Peer]] = None,
    ) -> None:
        """
        Broadcast a newly created local model as a full object message.

        This path is only for creator-side publication. The creator already knows that no
        remote peer has the object yet, so it can send the full object directly instead of
        first announcing inventory via IHAVE. Receiving peers then continue dissemination
        by announcing the object identifier through the normal IHAVE/IWANT gossip flow.

        :param model: Newly created model to broadcast.
        :param skip_peers: Optional set of peers that should not receive the payload.
        :return: None
        """
        handler = self._handlers_by_model_cls.get(type(model))
        if handler is None:
            msg = f"No replication handler registered for model type {type(model)!r}."
            raise TypeError(msg)
        self._multicast(
            handler.build_message(model),
            skip_peers=skip_peers,
        )

    def _has_object(self, item: GossipItem) -> bool:
        """
        Check whether a gossip item refers to an object stored locally.

        Unknown object types are treated as missing.

        :param item: Gossip item to check.
        :return: True if the referenced object is known locally, False otherwise.
        """
        handler = self._handlers_by_type.get(item.object_type)
        if handler is None:
            return False

        return handler.get_stored_model(item) is not None

    def _send_object(self, peer: Peer, item: GossipItem) -> None:
        """
        Send the full object referenced by a gossip item to a peer.

        The method resolves the appropriate replication handler, retrieves the locally
        stored model, converts it to its object message, and sends it to the requesting
        peer. If the object type is unknown or the object is not stored locally, no
        message is sent.

        :param peer: Peer that requested the object.
        :param item: Gossip item identifying the requested object.
        :return: None
        """
        handler = self._handlers_by_type.get(item.object_type)
        if handler is None:
            logger.debug(
                f"{self.my_peer}: Cannot send requested object "
                f"{item.object_type}:{item.object_uuid} because its type is unknown."
            )
            return

        stored_model = handler.get_stored_model(item)
        if stored_model is None:
            logger.debug(
                f"{self.my_peer}: Cannot send requested object "
                f"{item.object_type}:{item.object_uuid} because it is not stored locally."
            )
            return

        self._send_to_peer(peer, handler.build_message(stored_model))

    @lazy_wrapper(IHaveMessage)
    def on_ihave_message(self, peer: Peer, payload: IHaveMessage) -> None:
        """
        Handle an incoming IHAVE message from a peer.

        The method checks which announced objects are not stored locally and requests
        those missing objects from the sender using IWANT messages. Unknown object types
        are ignored.

        :param peer: Peer that sent the IHAVE message.
        :param payload: Received IHAVE message containing announced gossip items.
        :return: None
        """
        logger.debug(
            f"{self.my_peer}: Received {self._brief(payload)} from peer {peer}."
        )

        missing_items = [
            item
            for item in payload.decode_items()
            if item.object_type in self._handlers_by_type and not self._has_object(item)
        ]

        if not missing_items:
            logger.debug(f"{self.my_peer}: No unknown objects in IHAVE.")
            return

        for batch in batch_gossip_items(missing_items):
            self._send_to_peer(
                peer,
                IWantMessage.from_items(batch),
            )

    @lazy_wrapper(IWantMessage)
    def on_iwant_message(self, peer: Peer, payload: IWantMessage) -> None:
        """
        Handle an incoming IWANT message from a peer.

        The method sends the full object message for each requested gossip item, if the
        object type is supported and the object is stored locally. Unknown or missing
        objects are ignored by the object sending logic.

        :param peer: Peer that requested the objects.
        :param payload: Received IWANT message containing requested gossip items.
        :return: None
        """
        logger.debug(
            f"{self.my_peer}: Received {self._brief(payload)} from peer {peer}."
        )

        for item in payload.decode_items():
            self._send_object(peer, item)

    def _handle_object_message(
        self,
        peer: Peer,
        payload: BaseMessage[Any],
        object_type: ObjectType,
    ) -> None:
        """
        Handle an incoming full object message from a peer.

        The payload is converted to its model representation and passed to the replication
        handler for the corresponding object type. Newly stored objects trigger the data
        change callback and are announced to other peers with IHAVE. Objects that are
        already known or rejected by the repository are not propagated further.

        :param peer: Peer that sent the object message.
        :param payload: Received full object message.
        :param object_type: Type of democracy object contained in the message.
        :return: None
        :raises ValueError: If the replication handler returns an unexpected store status.
        """
        logger.debug(f"{self.my_peer}: Received {payload.brief()} from peer {peer}.")

        handler = self._handlers_by_type[object_type]
        model = payload.to_model()
        item = handler.build_item(model)
        store_status = handler.store_remote(model)

        if store_status is StoreStatus.ALREADY_PRESENT:
            logger.debug(
                f"{self.my_peer}: Already knew about {payload.brief()}. "
                f"Nothing updated."
            )
            return

        if store_status is StoreStatus.REJECTED:
            logger.debug(f"{self.my_peer}: Rejected {payload.brief()}.")
            return

        if store_status is StoreStatus.STORED:
            self.data_changed()
            self._announce_inventory([item], skip_peers={peer})
            return

        msg = f"Unexpected store status: {store_status}."
        raise ValueError(msg)
