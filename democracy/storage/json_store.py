import json
import os

from pathlib import Path
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar

T = TypeVar("T")


class JSONStore(Generic[T]):
    """
    Simple JSON-backed generic store for objects of type T.

    Args:
        path (Path): The file path to the JSON storage.
        model_factory (Callable[[Dict[str, Any]], T]): A factory function to create an object of type T from a dictionary.
        dictify (Callable[[T], Dict[str, Any]]): A function to convert an object of type T to a dictionary.
    """
    def __init__(self, path: Path, model_factory: Callable[[Dict[str, Any]], T], dictify: Callable[[T], Dict[str, Any]]):
        self.path = path
        self._model_factory = model_factory
        self._dictify = dictify
        self._data: List[T] = []
        self._load()

    def _load(self) -> bool:
        """
        Load data from the JSON file into the store.

        :return: True if data was loaded, False if the file does not exist.
        """
        if not self.path.exists():
            self._data = []
            return False

        with open(self.path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)

        self._data = [self._model_factory(item) for item in raw]

        return True

    def _save(self) -> None:
        """
        Save the current data in the store to the JSON file.

        :return: None
        """
        if not self.path.parent.exists():
            os.makedirs(self.path.parent, exist_ok=True)

        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump([self._dictify(obj) for obj in self._data], fh, indent=2)

    def get_all(self) -> List[T]:
        """
        Retrieve all objects from the store.

        :return: A copy of the list of all objects in the store.
        """
        return list(self._data)

    def get_by_attribute(self, attr_name: str, attr_value: Any) -> Optional[T]:
        """
        Retrieve an object by a specified attribute name and value.

        :param attr_name: The name of the attribute to search by.
        :param attr_value: The value of the attribute to match.
        :return: The object with the specified attribute value, or None if not found.
        """
        for item in self._data:
            if getattr(item, attr_name, None) == attr_value:
                return item

        return None

    def get(self, id: str) -> Optional[T]:
        """
        Retrieve an object by its ID (if the object has an "id" attribute).

        :param id: The ID of the object to retrieve.
        :return: The object with the specified ID, or None if not found.
        """
        return self.get_by_attribute("id", id)

    def add(self, obj: T) -> None:
        """
        Add a new object to the store.

        :param obj: The object to add.
        :return: None
        """
        self._data.append(obj)
        self._save()

    def replace(self, id: str, obj: T) -> bool:
        """
        Replace an existing object in the store by its ID (if the object has an "id" attribute).

        :param id: The ID of the object to replace.
        :param obj: The new object to replace the existing one.
        :return: True if the object was replaced, False if not found.
        """
        for i, item in enumerate(self._data):
            if getattr(item, "id", None) == id:
                self._data[i] = obj
                self._save()

                return True

        return False

    def delete(self, id: str) -> bool:
        """
        Delete an object from the store by its ID (if the object has an "id" attribute).

        :param id: The ID of the object to delete.
        :return: True if the object was deleted, False if not found.
        """
        for i, item in enumerate(self._data):
            if getattr(item, "id", None) == id:
                self._data.pop(i)
                self._save()

                return True

        return False

    def count_by_attribute(self, attr_name: str, attr_value: Any) -> int:
        """
        Count the number of objects that have a specified attribute name and value.

        :param attr_name: The name of the attribute to search by.
        :param attr_value: The value of the attribute to match.
        :return: The count of objects with the specified attribute value.
        """
        count = 0
        for item in self._data:
            if getattr(item, attr_name, None) == attr_value:
                count += 1
        return count