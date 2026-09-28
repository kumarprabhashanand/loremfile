"""A loremfile.dev that is not loremfile.dev.

Every test here runs against a loopback server that serves a handful of made-up fixtures.
The client reaches it through `LOREMFILE_BASE_URL`, which it accepts **only** for a
loopback address — so this fixture is also the reason that override exists, and
`test_only_loremfile_dev.py` is what keeps it from becoming a way to point the client
anywhere else.
"""

from __future__ import annotations

import hashlib
import http.server
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from loremfile_client import api


def entry(path: str, body: bytes, *, tags: list[str] | None = None) -> dict[str, Any]:
    fmt = path.split("/", 1)[0]
    return {
        "path": path,
        "format": fmt,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "mime": "application/octet-stream",
        "description": f"a {fmt} file",
        "tags": tags or [fmt],
        "status": "active",
    }


BODIES = {
    "pdf/small.pdf": b"%PDF-1.4 pretend\n",
    "pdf/other.pdf": b"%PDF-1.4 also pretend\n",
    "svg/square.svg": b"<svg xmlns='http://www.w3.org/2000/svg'/>\n",
    "txt/notes.txt": b"lorem ipsum\n",
}
MANIFEST: dict[str, Any] = {
    "catalog_version": "9.9.9",
    "count": len(BODIES),
    "fixtures": [
        *(entry(path, body) for path, body in BODIES.items()),
        {**entry("pdf/withdrawn.pdf", b"gone"), "status": "removed"},
    ],
}


class Handler(http.server.BaseHTTPRequestHandler):
    #: Set by a test to serve bytes that do not match the manifest.
    corrupt: set[str] = set()  # noqa: RUF012 - a plain class attribute the tests swap

    def do_GET(self) -> None:  # BaseHTTPRequestHandler's spelling, not ours
        path = self.path.lstrip("/")
        if path == "manifest.json":
            body = json.dumps(MANIFEST).encode()
        elif path in BODIES:
            body = b"tampered with" if path in self.corrupt else BODIES[path]
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: Any) -> None:
        pass


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    Handler.corrupt = set()
    httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}/"
    monkeypatch.setenv("LOREMFILE_BASE_URL", base)
    # Downloads pause between files out of politeness to the real host; nothing here is
    # the real host, and a test suite that sleeps is a test suite nobody runs.
    monkeypatch.setattr(api, "pace", lambda: None)
    yield base
    httpd.shutdown()


@pytest.fixture
def dest(tmp_path: Path) -> Path:
    return tmp_path / "fixtures"
