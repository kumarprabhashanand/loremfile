"""The one file a format's page starts with, and the one a visitor can preview (docs/05 §8).

A pure function of the manifest and the catalog's `expected_drift` marks, so the page's
"Start here" block and the `sample.{ext}` aliases read the same answer from one place.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from typing import Any

#: Formats whose page is a collection and not one file: an HLS playlist is useless without its
#: segments, and every `edge` file is broken on purpose.
NO_DEFAULT = frozenset({"hls", "edge"})

#: A media default is under this, so what a page offers to download or play is cheap. A media
#: format with no file that small has no default: `ogv` (3.8 MB) and `ts` (2.05 MB).
MEDIA_FAMILIES = frozenset({"audio", "video"})
MEDIA_LIMIT = 2_000_000

#: Where "the smallest ordinary valid file" lands on something that is a case rather than a
#: baseline. Each is the plainest file of its format, and the reason is printed in docs/05 §8.
OVERRIDES: Mapping[str, tuple[str, str]] = {
    "gif": ("gif/static-256x256.gif", "the smallest, `gif/1x1.gif`, is one pixel"),
    "gz": (
        "gz/lorem-1mb.txt.gz",
        "the smallest, `gz/multi-member-3.gz`, is three streams joined end to end",
    ),
    "tar": ("tar/3-text-files.tar", "the smallest is the gzipped copy of the same archive"),
    "zip": ("zip/3-text-files.zip", "the smallest, `zip/empty.zip`, has no entries"),
}

#: What a browser draws or plays itself, so a page may preview it. Not tiff, heic, aiff, mkv,
#: mov, avi or ts: a preview that works in one browser and shows a broken box in the rest is
#: worse than none.
PREVIEW: Mapping[str, str] = {
    **dict.fromkeys(("png", "jpg", "gif", "webp", "avif", "svg", "bmp", "ico"), "image"),
    **dict.fromkeys(("mp3", "wav", "flac", "ogg", "opus", "m4a", "aac"), "audio"),
    **dict.fromkeys(("mp4", "webm", "ogv"), "video"),
}


def eligible(
    entries: Iterable[Mapping[str, Any]], drifting: Collection[str]
) -> list[Mapping[str, Any]]:
    """Active, current, not deliberately broken, and not a file whose bytes only the CI
    reference fleet reproduces: the most-copied URL on the site must not have that property."""
    return [
        e
        for e in entries
        if e.get("status", "active") == "active"
        and not e.get("supersededBy")
        and not e.get("edge_case")
        and not e.get("aliasOf")
        and e["path"] not in drifting
    ]


def default_choice(
    fmt: str,
    family: str,
    entries: Sequence[Mapping[str, Any]],
    drifting: Collection[str],
    popular: Sequence[str],
) -> tuple[str, str] | None:
    """(path, basis) of a format's default, or None where it has none.

    The file in the home page's Popular list where one exists, otherwise the smallest ordinary
    valid file, unless OVERRIDES names a plainer one. A media file is under 2 MB or not
    eligible. `basis` is what the docs table prints: `popular`, `smallest` or `override`.
    """
    if fmt in NO_DEFAULT:
        return None
    pool = eligible([e for e in entries if e["format"] == fmt], drifting)
    if family in MEDIA_FAMILIES:
        pool = [e for e in pool if e["bytes"] < MEDIA_LIMIT]
    if not pool:
        return None
    paths = {e["path"] for e in pool}
    for path in popular:
        if path in paths:
            return path, "popular"
    if fmt in OVERRIDES:
        path = OVERRIDES[fmt][0]
        if path not in paths:
            raise ValueError(
                f"the default for {fmt} is overridden to {path}, which is not eligible"
            )
        return path, "override"
    return min(pool, key=lambda e: (e["bytes"], e["path"]))["path"], "smallest"
