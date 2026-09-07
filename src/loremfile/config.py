"""Single source of truth for hosts, limits and the fixed build clock (docs/06 §2).

Every module reads from here; nothing else hard-codes the host. ``OWNER`` and the
contact mailbox stay placeholders until Q-03 and Q-07 are answered — find them with
``grep -rn '<OWNER>' --exclude-dir=.git .``
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

OWNER: Final = "<OWNER>"  # GitHub owner; replace once Q-03 is recorded
SITE_HOST: Final = "loremfile.dev"
BASE_URL: Final = f"https://{SITE_HOST}/"
BUCKET: Final = "loremfile-public"

# 2020-01-01T00:00:00Z. Every clock a generator can see is pinned here so that two
# builds of the same catalog produce identical bytes (docs/05 §1 rule 2).
SOURCE_DATE_EPOCH: Final = 1577836800

MAX_FIXTURE_BYTES: Final = 100_000_000  # REQ-23
MAX_TOTAL_BYTES: Final = 8_000_000_000  # REQ-24
APPROX_TOLERANCE: Final = 0.05  # REQ-12

FIXTURE_CACHE_CONTROL: Final = "public, max-age=31536000, immutable, no-transform"
SITE_CACHE_CONTROL: Final = "public, max-age=300, must-revalidate"
ASSET_CACHE_CONTROL: Final = "public, max-age=31536000, immutable"

BUILD_DIR: Final = "build"  # build/fixtures/<path>, build/site/<key>

LICENSE: Final = "CC0-1.0"
LICENSE_URL: Final = "https://creativecommons.org/publicdomain/zero/1.0/"
SOURCE_URL: Final = f"https://github.com/{OWNER}/loremfile"
SCHEMA_VERSION: Final = 1
SCHEMA_URL: Final = f"{BASE_URL}schema/manifest-v{SCHEMA_VERSION}.json"


def repo_root() -> Path:
    """The repository root, derived from this file's location.

    ``src/loremfile/config.py`` → three parents up. Used by the catalog and manifest
    loaders so they work the same from any working directory.
    """
    return Path(__file__).resolve().parents[2]


def catalog_dir() -> Path:
    return repo_root() / "catalog"


def manifest_path() -> Path:
    return repo_root() / "manifest.json"


def sha256sums_path() -> Path:
    return repo_root() / "sha256sums.txt"


def formats_json_path() -> Path:
    return repo_root() / "formats.json"


def toolchain_digest() -> str:
    """The pinned image reference, read from tools/TOOLCHAIN_DIGEST."""
    return (repo_root() / "tools" / "TOOLCHAIN_DIGEST").read_text(encoding="utf-8").strip()
