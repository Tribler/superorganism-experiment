from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from democracy.event_publisher import DemocracyEventPublisher
from democracy.models.DTOs.issue_with_votes import IssueWithVotes
from democracy.models.DTOs.solution_with_votes import SolutionWithVotes
from democracy.models.issue import Issue
from democracy.models.issue_vote import IssueVote
from democracy.models.solution import Solution
from democracy.models.solution_vote import SolutionVote
from democracy.models.vote_record_result import VoteRecordResult
from democracy.storage.repository import DemocracyAppRepository


class DemocracyService:
    """
    Democracy service backed by an application repository.
    """

    def __init__(
        self,
        repository: DemocracyAppRepository,
        publisher: DemocracyEventPublisher,
    ) -> None:
        self._repository = repository
        self._publisher = publisher

    def get_all_issues_with_votes(self) -> List[IssueWithVotes]:
        return self._repository.get_all_issues_with_votes()

    def get_issue_with_votes(self, issue_id: UUID) -> Optional[IssueWithVotes]:
        return self._repository.get_issue_with_votes(issue_id)

    def get_solutions_for_issue_with_votes(
        self, issue_id: UUID
    ) -> List[SolutionWithVotes]:
        return self._repository.get_solutions_for_issue_with_votes(issue_id)

    def get_solution_with_votes(
        self, solution_id: UUID
    ) -> Optional[SolutionWithVotes]:
        return self._repository.get_solution_with_votes(solution_id)

    def create_issue(self, title: str, description: str, creator_id: UUID) -> Issue:
        issue = Issue(
            title=title,
            description=description,
            creator_id=creator_id,
        )
        self._repository.add_issue(issue)
        self._publisher.publish_issue(issue)
        return issue

    def vote_for_issue(self, voter_id: UUID, issue_id: UUID) -> Optional[IssueVote]:
        vote = IssueVote(
            voter_id=voter_id,
            issue_id=issue_id,
        )
        result = self._repository.record_issue_vote(vote)
        if result is not VoteRecordResult.CREATED:
            return None

        self._publisher.publish_issue_vote(vote)
        return vote

    def create_solution(
        self, title: str, description: str, creator_id: UUID, issue_id: UUID
    ) -> Solution:
        solution = Solution(
            title=title,
            description=description,
            creator_id=creator_id,
            issue_id=issue_id,
        )
        self._repository.add_solution(solution)
        self._publisher.publish_solution(solution)
        return solution

    def vote_for_solution(
        self, voter_id: UUID, solution_id: UUID
    ) -> Optional[SolutionVote]:
        vote = SolutionVote(
            voter_id=voter_id,
            solution_id=solution_id,
        )
        result = self._repository.record_solution_vote(vote)
        if result is not VoteRecordResult.CREATED:
            return None

        self._publisher.publish_solution_vote(vote)
        return vote
