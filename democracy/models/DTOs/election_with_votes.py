from dataclasses import dataclass

from models.election import Election


@dataclass
class ElectionWithVotes:
    """
    Represents an election along with its associated vote count.

    Attributes:
        election (Election): The election details.
        votes (int): The number of votes associated with the election.
    """
    election: Election
    votes: int