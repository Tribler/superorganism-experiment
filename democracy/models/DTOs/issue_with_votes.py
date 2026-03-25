from dataclasses import dataclass

from democracy.models.issue import Issue


@dataclass
class IssueWithVotes:
    """
    Represents an issue along with its associated vote count.

    Attributes:
        issue (Issue): The issue details.
        votes (int): The number of votes associated with the issue.
    """
    issue: Issue
    votes: int