from abc import ABC, abstractmethod
from typing import Generic, Type, TypeVar

from ipv8.messaging.payload_dataclass import DataClassPayload

TModel = TypeVar("TModel")
TMsg = TypeVar("TMsg", bound="BaseMessage")

class BaseMessage(DataClassPayload, ABC, Generic[TModel]):
    @property
    @abstractmethod
    def entity_id(self) -> str: ...

    @abstractmethod
    def brief(self) -> str:
        """Return a short human-readable description of the message."""
        pass

    @abstractmethod
    def to_model(self) -> TModel:
        """Convert message into domain model."""
        pass

    @classmethod
    @abstractmethod
    def from_model(cls: Type[TMsg], model: TModel) -> TMsg:
        """Create message from domain model."""
        pass
