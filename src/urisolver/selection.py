"""Selection types (§13)."""
from __future__ import annotations
from dataclasses import dataclass
from types import EllipsisType
from typing import Sequence, Union

@dataclass(frozen=True)
class Native:
    """Opaque pass-through wrapper declaring protocol coupling (§13)."""
    value: object

Selection = Union[int, slice, EllipsisType, tuple, Sequence[str], Native]
