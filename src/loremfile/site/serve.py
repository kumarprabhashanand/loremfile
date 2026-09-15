"""`loremfile site serve`: preview `build/site/` with the edge's routing (docs/06 §10)."""

from __future__ import annotations

import http.server
from pathlib import Path
from urllib.parse import unquote, urlsplit

from loremfile.site import routes


def resolve(site_dir: Path, request_path: str) -> tuple[str, Path] | None:
    """The key and file the edge would serve for a request path, or None for a 404."""
    path = unquote(urlsplit(request_path).path) or "/"
    if ".." in path.split("/"):
        return None
    key = routes.key_for(path)
    file = site_dir / routes.disk_path(key)
    # `/pdf.html` names the key `pdf.html`, which does not exist, not the page stored as pdf.html.
    if not key or routes.key_of(routes.disk_path(key)) != key:
        return None
    return (key, file) if file.is_file() else None


def handler(site_dir: Path, not_found: bytes) -> type[http.server.BaseHTTPRequestHandler]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._send(body=True)

        def do_HEAD(self) -> None:
            self._send(body=False)

        def _send(self, *, body: bool) -> None:
            found = resolve(site_dir, self.path)
            if found is None:
                status, data, mime, page = 404, not_found, "text/html; charset=utf-8", True
            else:
                key, file = found
                status, data, mime, page = (
                    200,
                    file.read_bytes(),
                    routes.content_type(key),
                    routes.is_page(key),
                )
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            if page:
                self.send_header("Content-Security-Policy", routes.SITE_CSP)
            self.end_headers()
            if body:
                self.wfile.write(data)

    return Handler


def serve(site_dir: Path, *, port: int) -> None:
    page = site_dir.parent / "site-404.html"
    not_found = page.read_bytes() if page.is_file() else b"not found\n"
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler(site_dir, not_found))
    server.serve_forever()
