from collections import Counter
from typing import List, Optional
from uuid import UUID

from models.DTOs.issue_with_votes import IssueWithVotes
from models.issue import Issue
from models.vote import Vote
from storage.json_store import JSONStore


class IssueRepository:
    """
    Compose IssueStore and VoteStore to return issues with their votes attached.

    Args:
        issue_store (JSONStore[Issue]): The JSON store for issues.
        vote_store (JSONStore[Vote]): The JSON store for votes.
    """
    def __init__(self, issue_store: JSONStore[Issue], vote_store: JSONStore[Vote]):
        self.issue_store = issue_store
        self.vote_store = vote_store

    def get_all(self) -> List[IssueWithVotes]:
        """
        Retrieve all issues along with their respective vote counts.

        :return: A list of IssuesWithVotes instances.
        """
        issues = self.issue_store.get_all()
        counts = Counter(v.issue_id for v in self.vote_store.get_all())

        return [
            IssueWithVotes(issue=e, votes=counts.get(e.id, 0))
            for e in issues
        ]

    def get(self, issue_id: UUID) -> Optional[IssueWithVotes]:
        """
        Retrieve a specific issue by its ID along with its vote count.

        :param issue_id: The ID of the issue to retrieve.
        :return: An IssueWithVotes instance if found, otherwise None.
        """
        e = self.issue_store.get(issue_id)

        if not e:
            return None

        votes = self.vote_store.count_by_attribute("issue_id", issue_id)

        return IssueWithVotes(issue=e, votes=votes)