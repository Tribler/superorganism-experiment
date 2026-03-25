from uuid import uuid4, UUID

from dataclasses import dataclass, field


@dataclass
class Person:
    """
    Represents a person with a unique identifier.

    Attributes:
        id (str): Unique identifier for the person.
    """
    id: UUID = field(default_factory=uuid4)