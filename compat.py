from __future__ import annotations

try:
    from enum import StrEnum
except ImportError:
    from backports.strenum import StrEnum

__all__ = ["StrEnum"]
