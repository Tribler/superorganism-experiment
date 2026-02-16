import uuid

from dataclasses import dataclass, field


@dataclass
class Person:
    """
    Represents a person with a unique identifier.

    Attributes:
        id (str): Unique identifier for the person.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))