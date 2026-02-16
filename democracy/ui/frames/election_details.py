import uuid
from tkinter import ttk, StringVar, IntVar

from models.DTOs.election_with_votes import ElectionWithVotes
from models.vote import Vote


class ElectionDetailFrame(ttk.Frame):
    """
    Displays a single election's details.
    Calls on_vote(vote) when the Approve button is clicked.

    Args:
        master: Parent widget.
        on_vote: Callback function when a vote is cast.
    """
    def __init__(self, master, on_vote=None, **kwargs):
        super().__init__(master, **kwargs)
        self.on_vote = on_vote

        self.election_id_var = StringVar()
        ttk.Label(self, text="Election ID:").grid(column=0, row=0, sticky="NW")
        ttk.Label(self, textvariable=self.election_id_var).grid(column=1, row=0, sticky="NW")

        self.creator_var = StringVar()
        ttk.Label(self, text="Creator:").grid(column=0, row=1, sticky="NW")
        ttk.Label(self, textvariable=self.creator_var).grid(column=1, row=1, sticky="NW")

        self.created_at_var = StringVar()
        ttk.Label(self, text="Created at:").grid(column=0, row=2, sticky="NW")
        ttk.Label(self, textvariable=self.created_at_var).grid(column=1, row=2, sticky="NW")

        self.title_var = StringVar()
        ttk.Label(self, text="Title:").grid(column=0, row=3, sticky="NW")
        ttk.Label(self, textvariable=self.title_var).grid(column=1, row=3, sticky="NW")

        ttk.Label(self, text="Description:").grid(column=0, row=4, sticky="NW")
        self.desc_var = StringVar()
        ttk.Label(self, textvariable=self.desc_var, wraplength=200).grid(column=1, row=4, sticky="NW")

        self.threshold_var = IntVar()
        ttk.Label(self, text="Threshold:").grid(column=0, row=5, sticky="NW")
        ttk.Label(self, textvariable=self.threshold_var).grid(column=1, row=5, sticky="NW")

        self.votes_var = IntVar()
        ttk.Label(self, text="Votes:").grid(column=0, row=6, sticky="NW")
        ttk.Label(self, textvariable=self.votes_var).grid(column=1, row=6, sticky="NW")
        ttk.Button(self, text="Approve", command=self._vote).grid(column=2, row=6, sticky="WE")

    def show(self, e: ElectionWithVotes):
        """
        Loads the election details into the frame.

        :param e: ElectionWithVotes to display.
        :return: None
        """
        self.election_id_var.set(e.election.id)
        self.creator_var.set(e.election.creator_id)
        self.created_at_var.set(e.election.created_at)
        self.title_var.set(e.election.title)
        self.desc_var.set(e.election.description or "")
        self.threshold_var.set(e.election.threshold)
        self.votes_var.set(e.votes)

    def _vote(self):
        """
        Handles voting and calls the on_vote callback.

        :return: None
        """
        v = Vote(
            id=str(uuid.uuid4()),
            voter_id=self.creator_var.get(),
            election_id=self.election_id_var.get(),
        )
        if self.on_vote:
            self.on_vote(v)
