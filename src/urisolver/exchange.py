"""Move one opaque request and return one opaque response.

This module does not know what the bytes mean. A pipe and a socket are the
same stream transport. HTTP POST is a third way to carry the same bytes.
An in-process call is the third communication type already used in this package.
"""
from __future__ import annotations

import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import BinaryIO, Callable, Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# A credential map is small. Refuse a frame that would allocate without bound.
_MAX_FRAME = 1_048_576
_LEN = struct.Struct(">I")

Handler = Callable[[bytes], bytes]


@runtime_checkable
class Exchange(Protocol):
    def exchange(self, request: bytes) -> bytes: ...


class DirectExchange:
    """Call a bytes handler in this process."""

    def __init__(self, handler: Handler) -> None:
        self._handler = handler

    def exchange(self, request: bytes) -> bytes:
        return self._handler(request)

    def close(self) -> None:
        return None


class StreamExchange:
    """Length-prefixed frames on a connected binary stream.

    Each message is a 4-byte big-endian length followed by that many bytes.
    A pipe and a socketpair both qualify. The caller writes a request and
    reads one response.
    """

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self._lock = threading.Lock()

    def exchange(self, request: bytes) -> bytes:
        with self._lock:
            _write_frame(self._stream, request)
            return _read_frame(self._stream)

    def close(self) -> None:
        self._stream.close()


class HttpExchange:
    """POST the payload and return the response body.

    The URL belongs to this transport. It is not part of the message.
    """

    def __init__(self, url: str, *, timeout: float = 30.0) -> None:
        self._url = url
        self._timeout = timeout

    def exchange(self, request: bytes) -> bytes:
        req = Request(self._url, data=request, method="POST")
        try:
            with urlopen(req, timeout=self._timeout) as resp:
                return resp.read()
        except HTTPError as exc:
            raise OSError(f"exchange HTTP {exc.code}") from None
        except URLError:
            raise OSError("exchange HTTP request failed") from None

    def close(self) -> None:
        return None


def serve_stream(stream: BinaryIO, handler: Handler) -> None:
    """Read frames from *stream*, write handler responses, until EOF."""
    try:
        while True:
            try:
                request = _read_frame(stream)
            except EOFError:
                return
            try:
                response = handler(request)
            except Exception:
                return
            _write_frame(stream, response)
    except (BrokenPipeError, ConnectionResetError, ValueError):
        return


class RunningHttpExchange:
    """Loopback HTTP POST server for one bytes handler."""

    def __init__(self, server: ThreadingHTTPServer, thread: threading.Thread, url: str) -> None:
        self._server = server
        self._thread = thread
        self.url = url

    def close(self) -> None:
        self._server.shutdown()
        self._thread.join(timeout=5)
        self._server.server_close()


def serve_http(handler: Handler, *, host: str = "127.0.0.1", port: int = 0) -> RunningHttpExchange:
    """Serve ``POST`` of raw bytes. The handler's return value is the body."""

    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:  # noqa: N802
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if length < 0 or length > _MAX_FRAME:
                self.send_error(400)
                return
            body = self.rfile.read(length)
            try:
                response = handler(body)
            except Exception:
                response = b""
                status = 500
            else:
                status = 200
            self.send_response(status)
            self.send_header("Content-Length", str(len(response)))
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, fmt: str, *args: object) -> None:
            return None

    server = ThreadingHTTPServer((host, port), _Handler)
    thread = threading.Thread(
        target=server.serve_forever, name="urisolver-exchange-http", daemon=True
    )
    thread.start()
    bound_host, bound_port = server.server_address[:2]
    url = f"http://{bound_host}:{bound_port}/"
    return RunningHttpExchange(server, thread, url)


def _write_frame(stream: BinaryIO, payload: bytes) -> None:
    if len(payload) > _MAX_FRAME:
        raise ValueError("exchange frame exceeds size limit")
    stream.write(_LEN.pack(len(payload)))
    stream.write(payload)
    flush = getattr(stream, "flush", None)
    if callable(flush):
        flush()


def _read_frame(stream: BinaryIO) -> bytes:
    try:
        raw_len = _read_exact(stream, _LEN.size)
    except EOFError:
        raise
    (length,) = _LEN.unpack(raw_len)
    if length > _MAX_FRAME:
        raise ValueError("exchange frame exceeds size limit")
    if length == 0:
        return b""
    return _read_exact(stream, length)


def _read_exact(stream: BinaryIO, count: int) -> bytes:
    buf = bytearray()
    while len(buf) < count:
        chunk = stream.read(count - len(buf))
        if not chunk:
            if not buf:
                raise EOFError
            raise ValueError("truncated exchange frame")
        buf.extend(chunk)
    return bytes(buf)
