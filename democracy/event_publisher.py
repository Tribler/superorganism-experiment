from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from democracy.models.issue import Issue
from democracy.models.issue_vote import IssueVote
from democracy.models.solution import Solution
from democracy.models.solution_vote import SolutionVote

if TYPE_CHECKING:
    from democracy.network.ipv8_thread import IPv8Thread


class DemocracyEventPublisher:
    """
    Publishes democracy domain events to the networking layer when available.
    """

    def __init__(self) -> None:
        self._worker: Optional[IPv8Thread] = None

    def attach_worker(self, worker: IPv8Thread) -> None:
        self._worker = worker

    def publish_issue(self, issue: Issue) -> None:
        if self._worker is not None:
            self._worker.broadcastIssue.emit(issue)

    def publish_issue_vote(self, vote: IssueVote) -> None:
        if self._worker is not None:
            self._worker.broadcastIssueVote.emit(vote)

    def publish_solution(self, solution: Solution) -> None:
        if self._worker is not None:
            self._worker.broadcastSolution.emit(solution)

    def publish_solution_vote(self, vote: SolutionVote) -> None:
        if self._worker is not None:
            self._worker.broadcastSolutionVote.emit(vote)
