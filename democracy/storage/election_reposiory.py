from collections import Counter
from typing import List, Optional

from models.DTOs.election_with_votes import ElectionWithVotes
from models.election import Election
from models.vote import Vote
from storage.json_store import JSONStore


class ElectionRepository:
    """
    Compose ElectionStore and VoteStore to return elections with their votes attached.

    Args:
        election_store (JSONStore[Election]): The JSON store for elections.
        vote_store (JSONStore[Vote]): The JSON store for votes.
    """
    def __init__(self, election_store: JSONStore[Election], vote_store: JSONStore[Vote]):
        self.election_store = election_store
        self.vote_store = vote_store

    def get_all(self) -> List[ElectionWithVotes]:
        """
        Retrieve all elections along with their respective vote counts.

        :return: A list of ElectionWithVotes instances.
        """
        elections = self.election_store.get_all()
        counts = Counter(v.election_id for v in self.vote_store.get_all())

        return [
            ElectionWithVotes(election=e, votes=counts.get(e.id, 0))
            for e in elections
        ]

    def get(self, election_id: str) -> Optional[ElectionWithVotes]:
        """
        Retrieve a specific election by its ID along with its vote count.

        :param election_id: The ID of the election to retrieve.
        :return: An ElectionWithVotes instance if found, otherwise None.
        """
        e = self.election_store.get(election_id)

        if not e:
            return None

        votes = self.vote_store.count_by_attribute("election_id", election_id)

        return ElectionWithVotes(election=e, votes=votes)