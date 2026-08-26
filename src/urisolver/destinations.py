"""Destinations and forms (§9–§12)."""
from __future__ import annotations
import os
from dataclasses import dataclass
from enum import Enum

class Form(str, Enum):
    NATIVE = "native"
    BYTES = "bytes"
    ARRAY = "array"
    TABLE = "table"
    PATH = "path"

class ReferencePolicy(str, Enum):
    COPY = "copy"
    HARDLINK = "hardlink"
    SYMLINK = "symlink"
    IN_PLACE = "in_place"

@dataclass(frozen=True)
class FileDestination:
    path: os.PathLike[str] | str
    overwrite: bool = False
    make_parents: bool = True
    mode: int | None = None
    reference: ReferencePolicy = ReferencePolicy.COPY
    media_type: str | None = None

@dataclass(frozen=True)
class MemoryDestination:
    form: Form = Form.NATIVE
    max_bytes: int | None = None
    media_type: str | None = None

Destination = FileDestination | MemoryDestination
