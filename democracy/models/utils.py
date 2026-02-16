from datetime import datetime, timezone
from typing import Any, Optional


def parse_datetime(value: Any) -> datetime:
    """
    Normalize various datetime representations to a UTC datetime.
    Accepts int/float (unix timestamp), ISO string or numeric string.

    :param value: The input value to parse.
    :return: A datetime object in UTC.
    """
    if value is None:
        raise ValueError("Cannot parse 'None' as datetime")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            try:
                return datetime.fromtimestamp(float(value), timezone.utc)
            except Exception:
                raise ValueError(f"Cannot parse string '{value}' as datetime")
    raise ValueError(f"Cannot parse '{value}' as datetime")
