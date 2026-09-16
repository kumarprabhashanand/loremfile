"""`site serve` routes a request the way the edge does (ADR-032)."""

from __future__ import annotations

from pathlib import Path

import pytest

from loremfile.site import serve


@pytest.fixture
def site(tmp_path: Path) -> Path:
    for name in ("index.html", "pdf.html", "_formats/pdf.json", "docs/faq.html", "docs.html"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    return tmp_path


@pytest.mark.parametrize(
    ("request_path", "key"),
    [
        ("/", "index.html"),
        ("/pdf", "pdf"),
        ("/pdf/?download=1", "pdf"),
        ("/pdf/index.json", "_formats/pdf.json"),
        ("/docs/", "docs"),
        ("/docs/faq", "docs/faq"),
    ],
)
def test_a_request_reaches_the_built_key(site: Path, request_path: str, key: str) -> None:
    found = serve.resolve(site, request_path)
    assert found is not None and found[0] == key


@pytest.mark.parametrize("request_path", ["/missing", "/../secret", "/%2e%2e/secret", "/pdf.html"])
def test_anything_else_is_a_404(site: Path, request_path: str) -> None:
    (site.parent / "secret").write_text("outside")
    assert serve.resolve(site, request_path) is None
