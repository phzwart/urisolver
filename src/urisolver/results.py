"""MaterializedResult (§10)."""
from __future__ import annotations
from dataclasses import dataclass, field
from urisolver.destinations import Destination, Form, MemoryDestination
from urisolver.redaction import redact_uri
from urisolver.selection import Selection

@dataclass(frozen=True)
class MaterializedResult:
    value: object
    source_uri: str
    resolved_uri: str
    protocol: str
    destination: Destination
    form: Form
    media_type: str | None
    size_bytes: int | None
    selection: Selection | None
    is_reference: bool
    strategy: str
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __repr__(self) -> str:
        src = redact_uri(self.source_uri)
        resolved = redact_uri(self.resolved_uri)
        value_repr = "<omitted>" if isinstance(self.destination, MemoryDestination) else repr(self.value)
        return (
            f"MaterializedResult(value={value_repr}, source_uri={src!r}, "
            f"resolved_uri={resolved!r}, protocol={self.protocol!r}, form={self.form!r}, "
            f"media_type={self.media_type!r}, is_reference={self.is_reference!r}, "
            f"strategy={self.strategy!r})"
        )
