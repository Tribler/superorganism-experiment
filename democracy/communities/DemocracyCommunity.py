from typing import Callable, Optional, Set, TypeVar

from ipv8.community import Community, CommunitySettings
from ipv8.lazy_community import lazy_wrapper
from ipv8.peer import Peer

from config import COMMUNICATION_INTERVAL
from constants import COMMUNITY_ID
from messages.base_message import BaseMessage
from messages.issue_message import IssueMessage
from messages.vote_message import VoteMessage
from models.issue import Issue
from models.vote import Vote
from storage.json_store import JSONStore

TModel = TypeVar("TModel")
TMsg = TypeVar("TMsg", bound=BaseMessage)

class DemocracyCommunity(Community):
    """
    Community to manage and propagate issues and votes among peers.
    1. On start, broadcasts all known issues to connected peers.
    2. On receiving an issue, adds it to the store if unknown and propagates it further.
    3. Provides a method to broadcast newly created issues to peers.

    Args:
        settings (CommunitySettings): Configuration for the community, including stores and callbacks.
    """
    community_id = COMMUNITY_ID

    def __init__(self, settings: CommunitySettings) -> None:
        super().__init__(settings)

        self.issue_store: JSONStore[Issue] = settings.issue_store
        self.vote_store: JSONStore[Vote] = settings.vote_store
        self.data_changed = settings.data_changed

        # Register the message handlers for messages.
        self.add_message_handler(IssueMessage, self.on_issue_message)
        self.add_message_handler(VoteMessage, self.on_vote_message)

    def _multicast(self, payload: BaseMessage, skip_peers: Optional[Set[Peer]] = None) -> None:
        """
        Multicasts a given message payload to all connected peers and skips the peers in skip_peers.

        :param payload: Message to broadcast.
        :param skip_peers: Set of peers to skip when broadcasting.
        :return: None
        """
        if skip_peers is None:
            skip_peers = set()

        for peer in self.get_peers():
            if peer in skip_peers:
                continue
            print(f"{self.my_peer}: Broadcasting {payload.brief()} to peer {peer}.")
            self.ez_send(peer, payload)

    def _broadcast_store(self, store, to_message: Callable[[TModel], BaseMessage], label: str) -> None:
        items = store.get_all()

        if not items:
            return

        print(f"{self.my_peer}: Broadcasting {len(items)} {label} items to peers.")

        for item in items:
            self._multicast(to_message(item))

    def on_start(self) -> None:
        """
        Called when the community starts. Sets up periodic broadcasting of known issues to peers.

        :return: None
        """
        async def periodic_communication() -> None:
            """
            Periodically broadcasts all known issues and votes to connected peers.

            :return: None
            """
            self._broadcast_store(
                self.issue_store,
                IssueMessage.from_model,
                label="issues"
            )

            self._broadcast_store(
                self.vote_store,
                VoteMessage.from_model,
                label="votes",
            )

        # We register an asyncio task with this overlay.
        # This makes sure that the task ends when this overlay is unloaded.
        # We call the "periodic_communication" function every minute, starting now.
        self.register_task("start_communication", periodic_communication, interval=COMMUNICATION_INTERVAL, delay=0)

    def _handle_incoming_message(self, peer: Peer, payload: TMsg, store, on_added: Callable[[], None]) -> None:
        print(f"{self.my_peer}: Received {payload.brief()} from peer {peer}.")

        if store.get(payload.entity_id):
            print(f"{self.my_peer}: Already knew about {payload.brief()}. Nothing updated.")
            return

        model = payload.to_model()
        store.add(model)
        on_added()

        self._multicast(payload, skip_peers={peer})

    @lazy_wrapper(IssueMessage)
    def on_issue_message(self, peer: Peer, payload: IssueMessage) -> None:
        """
        Handles incoming issue messages from peers. Adds unknown issues to the store and propagates them.

        :param peer: Peer that sent the message.
        :param payload: Received issue message.
        :return: None
        """
        self._handle_incoming_message(peer, payload, store=self.issue_store, on_added=self.data_changed)

    def on_create_issue(self, issue: Issue) -> None:
        """
        Broadcasts a newly created issue to all connected peers.

        :param issue: Issue to broadcast.
        :return: None
        """
        self._multicast(IssueMessage.from_model(issue))

    @lazy_wrapper(VoteMessage)
    def on_vote_message(self, peer: Peer, payload: VoteMessage) -> None:
        """
        Handles incoming vote messages from peers. Adds unknown votes to the store and propagates them.

        :param peer: Peer that sent the message.
        :param payload: Received vote message.
        :return: None
        """
        self._handle_incoming_message(peer, payload, store=self.vote_store, on_added=self.data_changed)

    def on_vote(self, vote: Vote) -> None:
        """
        Broadcasts a newly created vote to all connected peers.

        :param vote: Vote to broadcast.
        :return: None
        """
        self._multicast(VoteMessage.from_model(vote))
