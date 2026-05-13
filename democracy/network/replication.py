from __future__ import annotations

import sqlite3

from enum import Enum
from typing import Any, Callable, Generic, Protocol, TypeVar
from uuid import UUID

from democracy.models.issue import Issue
from democracy.models.issue_vote import IssueVote
from democracy.models.solution import Solution
from democracy.models.solution_vote import SolutionVote
from democracy.models.vote_record_result import VoteRecordResult
from democracy.network.messages.base_message import BaseMessage
from democracy.network.messages.gossip_messages import GossipItem
from democracy.network.messages.issue_message import IssueMessage
from democracy.network.messages.issue_vote_message import IssueVoteMessage
from democracy.network.messages.solution_message import SolutionMessage
from democracy.network.messages.solution_vote_message import SolutionVoteMessage
from democracy.network.object_type import ObjectType
from democracy.storage.repository import DemocracySyncRepository


class HasUuidId(Protocol):
    """Protocol for models that expose a UUID identifier."""

    @property
    def id(self) -> UUID: ...


TModel = TypeVar("TModel", bound=HasUuidId)


class StoreStatus(Enum):
    """Result of attempting to store an incoming object."""
    STORED = "stored"
    ALREADY_PRESENT = "already_present"
    REJECTED = "rejected"


class ReplicationHandler(Generic[TModel]):
    """
    Handles replication logic for one type of democracy object.

    A replication handler connects an object type to its model class, network message
    class, and repository operations. This allows the gossip layer to treat issues, votes,
    solutions, and solution votes in a uniform way.
    """

    def __init__(
        self,
        *,
        object_type: ObjectType,
        model_cls: type[TModel],
        message_cls: type[BaseMessage[TModel]],
        get_all_models: Callable[[], list[TModel]],
        get_one: Callable[[UUID], TModel | None],
        add_one: Callable[[TModel], None],
    ) -> None:
        """
        Initialize a replication handler for one object type.

        :param object_type: Object type handled by this replication handler.
        :param model_cls: Model class used for this object type.
        :param message_cls: Message class used to send this object type.
        :param get_all_models: Function returning all stored models of this type.
        :param get_one: Function returning one stored model by UUID.
        :param add_one: Function storing one model in the local repository.
        """
        self.object_type = object_type
        self.model_cls = model_cls
        self.message_cls = message_cls
        self._get_all_models = get_all_models
        self._get_one = get_one
        self._add_one = add_one

    def get_all_models(self) -> list[TModel]:
        """
        Return all locally stored models handled by this replication handler.

        :return: List of stored models.
        """
        return self._get_all_models()

    def build_item(self, model: TModel) -> GossipItem:
        """
        Build a gossip item reference for a model.

        :param model: Model to reference.
        :return: Gossip item containing the model's object type and UUID.
        """
        return GossipItem(
            object_type=self.object_type,
            object_uuid=model.id,
        )

    def get_stored_model(self, item: GossipItem) -> TModel | None:
        """
        Return the locally stored model referenced by a gossip item.

        :param item: Gossip item referencing the requested model.
        :return: Stored model if present, otherwise None.
        """
        return self._get_one(item.object_uuid)

    def build_message(self, model: TModel) -> BaseMessage[TModel]:
        """
        Build a network message for a model.

        :param model: Model to convert into a message.
        :return: Message containing the model data.
        """
        return self.message_cls.from_model(model)

    def store_remote(self, model: TModel) -> StoreStatus:
        """
        Store a model received from a remote peer.

        Existing models are not stored again. Repository integrity errors are treated as
        rejected objects.

        :param model: Remote model to store.
        :return: Status describing whether the model was stored, already known, or
                 rejected.
        """
        if self.get_stored_model(self.build_item(model)) is not None:
            return StoreStatus.ALREADY_PRESENT

        try:
            self._add_one(model)
        except sqlite3.IntegrityError:
            return StoreStatus.REJECTED
        return StoreStatus.STORED


TVoteModel = TypeVar("TVoteModel", bound=HasUuidId)


class VoteReplicationHandler(ReplicationHandler[TVoteModel], Generic[TVoteModel]):
    """
    Handles replication logic for vote objects.

    This handler extends the generic replication handler with vote-specific storage logic.
    Instead of directly adding a vote to the repository, it uses the vote recording
    function so duplicate-vote rules are applied consistently.
    """

    def __init__(
        self,
        *,
        object_type: ObjectType,
        model_cls: type[TVoteModel],
        message_cls: type[BaseMessage[TVoteModel]],
        get_all_models: Callable[[], list[TVoteModel]],
        get_one: Callable[[UUID], TVoteModel | None],
        add_one: Callable[[TVoteModel], None],
        record_vote: Callable[[TVoteModel], VoteRecordResult],
    ) -> None:
        """
        Initialize a vote replication handler.

        :param object_type: Object type handled by this replication handler.
        :param model_cls: Vote model class used for this object type.
        :param message_cls: Message class used to send this vote type.
        :param get_all_models: Function returning all stored votes of this type.
        :param get_one: Function returning one stored vote by UUID.
        :param add_one: Function storing one vote in the local repository.
        :param record_vote: Function that records a vote while enforcing vote-specific
                            validation rules.
        """

        super().__init__(
            object_type=object_type,
            model_cls=model_cls,
            message_cls=message_cls,
            get_all_models=get_all_models,
            get_one=get_one,
            add_one=add_one,
        )
        self._record_vote = record_vote

    def store_remote(self, model: TVoteModel) -> StoreStatus:
        """
        Store a vote received from a remote peer.

        Existing votes are not stored again. The vote is recorded through the
        vote-specific repository method so duplicate voting is handled correctly.
        Repository integrity errors are treated as rejected votes.

        :param model: Remote vote model to store.
        :return: Status describing whether the vote was stored, already known, or
                 rejected.
        """
        if self.get_stored_model(self.build_item(model)) is not None:
            return StoreStatus.ALREADY_PRESENT

        try:
            result = self._record_vote(model)
        except sqlite3.IntegrityError:
            return StoreStatus.REJECTED
        if result is VoteRecordResult.ALREADY_VOTED:
            return StoreStatus.ALREADY_PRESENT
        return StoreStatus.STORED


def build_replication_handlers(
    repository: DemocracySyncRepository,
) -> list[ReplicationHandler[Any]]:
    """
    Build the replication handlers for all object types managed by the democracy protocol.

    Each handler connects an object type to its model class, network message class, and
    repository operations. Vote objects use specialized vote handlers so that incoming
    votes are also recorded in the corresponding vote store.

    :param repository: Repository used to retrieve, store, and record replicated objects.
    :return: List of replication handlers for issues, issue votes, solutions, and solution
             votes.
    """
    issue_handler: ReplicationHandler[Issue] = ReplicationHandler(
        object_type=ObjectType.ISSUE,
        model_cls=Issue,
        message_cls=IssueMessage,
        get_all_models=repository.get_all_issues,
        get_one=repository.get_issue,
        add_one=repository.add_issue,
    )
    issue_vote_handler: ReplicationHandler[IssueVote] = VoteReplicationHandler(
        object_type=ObjectType.ISSUE_VOTE,
        model_cls=IssueVote,
        message_cls=IssueVoteMessage,
        get_all_models=repository.get_all_issue_votes,
        get_one=repository.get_issue_vote,
        add_one=repository.add_issue_vote,
        record_vote=repository.record_issue_vote,
    )
    solution_handler: ReplicationHandler[Solution] = ReplicationHandler(
        object_type=ObjectType.SOLUTION,
        model_cls=Solution,
        message_cls=SolutionMessage,
        get_all_models=repository.get_all_solutions,
        get_one=repository.get_solution,
        add_one=repository.add_solution,
    )
    solution_vote_handler: ReplicationHandler[SolutionVote] = VoteReplicationHandler(
        object_type=ObjectType.SOLUTION_VOTE,
        model_cls=SolutionVote,
        message_cls=SolutionVoteMessage,
        get_all_models=repository.get_all_solution_votes,
        get_one=repository.get_solution_vote,
        add_one=repository.add_solution_vote,
        record_vote=repository.record_solution_vote,
    )
    return [
        issue_handler,
        issue_vote_handler,
        solution_handler,
        solution_vote_handler,
    ]
