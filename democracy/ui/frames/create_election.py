from tkinter import IntVar, StringVar, ttk
from models.election import Election
import uuid


class CreateElectionFrame(ttk.Frame):
    """
    Frame for creating an election. Calls on_create(election) on submit.

    Args:
        master: Parent widget.
        on_create: Callback function when an election is created.
    """
    def __init__(self, master, on_create=None, **kwargs):
        super().__init__(master, **kwargs)
        self.on_create = on_create

        ttk.Label(self, text="Title:").grid(column=0, row=0, sticky="WE")
        self.title_var = StringVar()
        ttk.Entry(self, textvariable=self.title_var).grid(column=1, row=0, sticky="WE")

        ttk.Label(self, text="Description:").grid(column=0, row=1, sticky="WE")
        self.description_var = StringVar()
        ttk.Entry(self, textvariable=self.description_var).grid(column=1, row=1, sticky="WE")

        ttk.Label(self, text="Threshold:").grid(column=0, row=2, sticky="WE")
        self.threshold_var = IntVar(value=50)
        ttk.Entry(self, textvariable=self.threshold_var).grid(column=1, row=2, sticky="WE")

        ttk.Button(self, text="Create", command=self._create).grid(column=0, row=3, columnspan=2, sticky="WE")

    def _create(self):
        """
        Handles creation of a new election and calls the on_create callback.

        :return: None
        """
        e = Election(
            id=str(uuid.uuid4()),
            title=self.title_var.get(),
            description=self.description_var.get(),
            threshold=self.threshold_var.get()
        )

        if self.on_create:
            self.on_create(e)

        # Clear fields
        self.title_var.set("")
        self.description_var.set("")
        self.threshold_var.set(50)