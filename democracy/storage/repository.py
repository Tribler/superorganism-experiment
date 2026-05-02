from __future__ import annotations

from typing import List, Optional, Protocol
from uuid import UUID

from democracy.models.DTOs.issue_with_votes import IssueWithVotes
from democracy.models.DTOs.solution_with_votes import SolutionWithVotes
from democracy.models.issue import Issue
from democracy.models.issue_vote import IssueVote
from democracy.models.solution import Solution
from democracy.models.solution_vote import SolutionVote
from democracy.models.vote_record_result import VoteRecordResult


class ClosableRepository(Protocol):
    def close(self) -> None: ...


class DemocracyReadRepository(Protocol):
    """
    Application-facing read access for democracy data.
    """

    def get_all_issues_with_votes(self) -> List[IssueWithVotes]: ...

    def get_issue_with_votes(self, issue_id: UUID) -> Optional[IssueWithVotes]: ...

    def get_all_solutions_with_votes(self) -> List[SolutionWithVotes]: ...

    def get_solution_with_votes(
        self, solution_id: UUID
    ) -> Optional[SolutionWithVotes]: ...

    def get_solutions_for_issue_with_votes(
        self, issue_id: UUID
    ) -> List[SolutionWithVotes]: ...


class DemocracyWriteRepository(Protocol):
    """
    Application-facing write access and write-side domain checks.
    """

    def add_issue(self, issue: Issue) -> None: ...

    def record_issue_vote(self, vote: IssueVote) -> VoteRecordResult: ...

    def add_solution(self, solution: Solution) -> None: ...

    def record_solution_vote(self, vote: SolutionVote) -> VoteRecordResult: ...


class DemocracySyncRepository(ClosableRepository, Protocol):
    """
    Raw entity access used by the replication/synchronization layer.
    """

    def get_issue(self, issue_id: UUID) -> Optional[Issue]: ...

    def get_all_issues(self) -> List[Issue]: ...

    def get_issue_vote(self, vote_id: UUID) -> Optional[IssueVote]: ...

    def get_all_issue_votes(self) -> List[IssueVote]: ...

    def add_issue(self, issue: Issue) -> None: ...

    def add_issue_vote(self, vote: IssueVote) -> None: ...

    def get_solution(self, solution_id: UUID) -> Optional[Solution]: ...

    def get_all_solutions(self) -> List[Solution]: ...

    def add_solution_vote(self, vote: SolutionVote) -> None: ...

    def get_solution_vote(self, vote_id: UUID) -> Optional[SolutionVote]: ...

    def get_all_solution_votes(self) -> List[SolutionVote]: ...

    def add_solution(self, solution: Solution) -> None: ...


class DemocracyAppRepository(
    DemocracyReadRepository, DemocracyWriteRepository, Protocol
):
    """
    Repository surface used by the application service.
    """


class DemocracyRepository(
    DemocracyReadRepository, DemocracyWriteRepository, DemocracySyncRepository, Protocol
):
    """
    Full repository surface implemented by concrete persistence backends.
    """
