"""HTTP client for remote namespace services (§21)."""
from __future__ import annotations
import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from typing import Any
from urisolver.errors import NamespaceResolutionError
from urisolver.namespaces.base import NamespaceRequestContext, NamespaceResolution, ResolutionStatus

class NamespaceClient:
    def __init__(self, base_url: str, *, token: str | None = None, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def resolve_namespace(self, identifier: str, context: NamespaceRequestContext) -> NamespaceResolution:
        body = json.dumps({"identifier": identifier}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/resolve",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise NamespaceResolutionError(f"namespace service HTTP {exc.code}") from None
        except urllib.error.URLError:
            raise NamespaceResolutionError("namespace service unreachable") from None
        return _parse(payload)

def _parse(payload: dict[str, Any]) -> NamespaceResolution:
    status = ResolutionStatus(payload["status"])
    expires_at = None
    if payload.get("expires_at"):
        expires_at = datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00"))
    retry_after = None
    if payload.get("retry_after") is not None:
        retry_after = timedelta(seconds=int(payload["retry_after"]))
    return NamespaceResolution(
        status=status,
        uri=payload.get("uri"),
        expires_at=expires_at,
        etag=payload.get("etag"),
        retry_after=retry_after,
        detail=payload.get("detail"),
    )
