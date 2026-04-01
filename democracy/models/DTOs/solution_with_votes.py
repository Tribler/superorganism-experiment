from dataclasses import dataclass

from democracy.models.issue import Issue
from democracy.models.solution import Solution


@dataclass
class SolutionWithVotes:
    """
    Represents a solution along with its associated vote count.

    Attributes:
        solution (Solution): The solution details.
        votes (int): The number of votes associated with the solution.
    """
    solution: Solution
    votes: int
    status_text: str = ""
    highlighted: bool = False