"""ResourceInfo and Kind (§7)."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

class Kind(str, Enum):
    FILE = "file"
    ARRAY = "array"
    TABLE = "table"
    CONTAINER = "container"
    OPAQUE = "opaque"

@dataclass(frozen=True)
class ResourceInfo:
    uri: str
    resolved_uri: str
    protocol: str
    kind: Kind
    exists: bool
    media_type: str | None = None
    size_bytes: int | None = None
    shape: tuple[int, ...] | None = None
    dtype: str | None = None
    canonical_media_type: str | None = None
    label: str | None = None
