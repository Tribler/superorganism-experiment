from tkinter import ttk
from typing import Callable, List

from models.DTOs.election_with_votes import ElectionWithVotes

class ElectionListFrame(ttk.Frame):
    """
    Frame that displays a list of elections in a treeview.
    Calls on_select(election_id) when an election is selected.

    Args:
        master: Parent widget.
        on_select: Callback function when an election is selected.
    """
    def __init__(self, master, on_select: Callable[[str], None]=None, **kwargs):
        super().__init__(master, **kwargs)
        self.on_select = on_select

        # Let the treeview expand to fill this frame
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(self, columns=("id","title","creator","threshold","votes",), show="headings", selectmode="browse")
        self.tree.heading("id", text="Election ID")
        self.tree.heading("title", text="Title")
        self.tree.heading("creator", text="Creator")
        self.tree.heading("threshold", text="Threshold")
        self.tree.heading("votes", text="Votes")
        self.tree.grid(row=0, column=0, sticky="NSEW")

        # Vertical scrollbar that also expands nicely
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.grid(row=0, column=1, sticky="NS")

        self.tree.bind("<<TreeviewSelect>>", self._on_select)

    def load(self, elections: List[ElectionWithVotes]):
        """
        Loads the list of elections into the treeview.

        :param elections: List of ElectionWithVotes to load.
        :return: None
        """
        self.tree.delete(*self.tree.get_children())
        for e in elections:
            self.tree.insert("", "end", iid=e.election.id, values=(e.election.id, e.election.title, e.election.creator_id, e.election.threshold, e.votes))

    def _on_select(self, _evt):
        """
        Handles selection of an election in the treeview.

        :param _evt: Event object (not used).
        :return: None
        """
        sel = self.tree.selection()
        if sel and self.on_select:
            self.on_select(sel[0])