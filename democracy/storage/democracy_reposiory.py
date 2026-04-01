from collections import Counter
from typing import List, Optional
from uuid import UUID

from democracy.models.DTOs.issue_with_votes import IssueWithVotes
from democracy.models.DTOs.solution_with_votes import SolutionWithVotes
from democracy.models.issue import Issue
from democracy.models.issue_vote import IssueVote
from democracy.models.solution import Solution
from democracy.models.solution_vote import SolutionVote
from democracy.storage.json_store import JSONStore


class DemocracyRepository:
    """
    Compose IssueStore, SolutionStore, IssueVoteStore and SolutionVoteStore
    to return issues and solutions with their votes attached.

    Args:
        issue_store (JSONStore[Issue]): The JSON store for issues.
        solution_store (JSONStore[Solution]): The JSON store for solutions.
        issue_vote_store (JSONStore[IssueVote]): The JSON store for issue votes.
        solution_vote_store (JSONStore[SolutionVote]): The JSON store for solution votes.
    """

    def __init__(
        self,
        issue_store: JSONStore[Issue],
        issue_vote_store: JSONStore[IssueVote],
        solution_store: JSONStore[Solution],
        solution_vote_store: JSONStore[SolutionVote],
    ):
        self.issue_store = issue_store
        self.issue_vote_store = issue_vote_store
        self.solution_store = solution_store
        self.solution_vote_store = solution_vote_store

    # -----------------------------
    # Issues
    # -----------------------------
    def get_all_issues_with_votes(self) -> List[IssueWithVotes]:
        """
        Retrieve all issues along with their respective vote counts.

        :return: A list of IssueWithVotes instances.
        """
        issues = self.issue_store.get_all()
        counts = Counter(v.issue_id for v in self.issue_vote_store.get_all())

        return [
            IssueWithVotes(issue=issue, votes=counts.get(issue.id, 0))
            for issue in issues
        ]

    def get_issue_with_votes(self, issue_id: UUID) -> Optional[IssueWithVotes]:
        """
        Retrieve a specific issue by its ID along with its vote count.

        :param issue_id: The ID of the issue to retrieve.
        :return: An IssueWithVotes instance if found, otherwise None.
        """
        issue = self.issue_store.get(issue_id)

        if not issue:
            return None

        votes = self.issue_vote_store.count_by_attribute("issue_id", issue_id)

        return IssueWithVotes(issue=issue, votes=votes)

    def get_issue(self, issue_id: UUID) -> Optional[Issue]:
        """
        Retrieve a specific issue by its ID.

        :param issue_id: The ID of the issue to retrieve.
        :return: The Issue if found, otherwise None.
        """
        return self.issue_store.get(issue_id)

    def has_user_voted_for_issue(self, voter_id: UUID, issue_id: UUID) -> bool:
        """
        Check whether a user has already voted for a given issue.

        :param voter_id: The ID of the voter.
        :param issue_id: The ID of the issue.
        :return: True if the user has already voted, otherwise False.
        """
        return any(
            vote.voter_id == voter_id and vote.issue_id == issue_id
            for vote in self.issue_vote_store.get_all()
        )

    # -----------------------------
    # Solutions
    # -----------------------------
    def get_all_solutions_with_votes(self) -> List[SolutionWithVotes]:
        """
        Retrieve all solutions along with their respective vote counts.

        :return: A list of SolutionWithVotes instances.
        """
        solutions = self.solution_store.get_all()
        counts = Counter(v.solution_id for v in self.solution_vote_store.get_all())

        return [
            SolutionWithVotes(solution=solution, votes=counts.get(solution.id, 0))
            for solution in solutions
        ]

    def get_solution_with_votes(self, solution_id: UUID) -> Optional[SolutionWithVotes]:
        """
        Retrieve a specific solution by its ID along with its vote count.

        :param solution_id: The ID of the solution to retrieve.
        :return: A SolutionWithVotes instance if found, otherwise None.
        """
        solution = self.solution_store.get(solution_id)

        if not solution:
            return None

        votes = self.solution_vote_store.count_by_attribute("solution_id", solution_id)

        return SolutionWithVotes(solution=solution, votes=votes)

    def get_solution(self, solution_id: UUID) -> Optional[Solution]:
        """
        Retrieve a specific solution by its ID.

        :param solution_id: The ID of the solution to retrieve.
        :return: The Solution if found, otherwise None.
        """
        return self.solution_store.get(solution_id)

    def get_solutions_for_issue_with_votes(self, issue_id: UUID) -> List[SolutionWithVotes]:
        """
        Retrieve all solutions belonging to a specific issue along with their vote counts.

        :param issue_id: The ID of the parent issue.
        :return: A list of SolutionWithVotes instances.
        """
        solutions = [
            solution
            for solution in self.solution_store.get_all()
            if solution.issue_id == issue_id
        ]
        counts = Counter(v.solution_id for v in self.solution_vote_store.get_all())

        return [
            SolutionWithVotes(solution=solution, votes=counts.get(solution.id, 0))
            for solution in solutions
        ]

    def get_solutions_for_issue(self, issue_id: UUID) -> List[Solution]:
        """
        Retrieve all solutions belonging to a specific issue.

        :param issue_id: The ID of the parent issue.
        :return: A list of Solution instances.
        """
        return [
            solution
            for solution in self.solution_store.get_all()
            if solution.issue_id == issue_id
        ]

    def has_user_voted_for_solution(self, voter_id: UUID, solution_id: UUID) -> bool:
        """
        Check whether a user has already voted for a given solution.

        :param voter_id: The ID of the voter.
        :param solution_id: The ID of the solution.
        :return: True if the user has already voted, otherwise False.
        """
        return any(
            vote.voter_id == voter_id and vote.solution_id == solution_id
            for vote in self.solution_vote_store.get_all()
        )