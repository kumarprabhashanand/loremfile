"""infra/token-expiry.json drives the rotation reminder, so it has to stay honest.

It holds dates only — never a secret. A stale or malformed date here means the
`rotation-due` issue never opens and a token expires silently, taking deploy, infra and
health with it (docs/08 §6, docs/11 §7.3).
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import pytest

EXPIRY = Path(__file__).resolve().parents[2] / "infra" / "token-expiry.json"
EXPECTED = {"T1", "T2", "T4"}

#: The secret names docs/09 §2 says must exist in the `production` environment.
SECRET_NAMES = {
    "CLOUDFLARE_API_TOKEN",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "CLOUDFLARE_ANALYTICS_TOKEN",
}


def rows() -> dict[str, dict]:
    data = json.loads(EXPIRY.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def test_file_exists_and_covers_every_token() -> None:
    assert EXPIRY.is_file(), "infra/token-expiry.json is missing"
    assert set(rows()) == EXPECTED


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_each_row_has_a_parseable_iso_date(key: str) -> None:
    row = rows()[key]
    parsed = dt.date.fromisoformat(row["expires"])
    assert parsed.year >= 2026


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_each_row_names_its_token_and_secret(key: str) -> None:
    row = rows()[key]
    assert row["name"].startswith("loremfile-ci-")
    for name in row["secret"].replace(" / ", " ").split():
        assert name in SECRET_NAMES, f"{name} is not a secret docs/09 §2 declares"


def test_no_secret_value_leaked_into_the_file() -> None:
    """The file records names and dates. A value here would be a live credential in git."""
    text = EXPIRY.read_text(encoding="utf-8")
    # Cloudflare tokens are 40 chars of [A-Za-z0-9_-]; R2 keys are 32+ hex.
    suspicious = re.findall(r'"[A-Za-z0-9_-]{40,}"', text)
    assert not suspicious, f"looks like a credential, not a date: {suspicious}"


def test_expiry_dates_are_in_the_future() -> None:
    """A date in the past means the reminder already fired and was missed."""
    stale = [
        f"{k} ({v['name']}) expired {v['expires']}"
        for k, v in rows().items()
        if dt.date.fromisoformat(v["expires"]) < dt.date.today()
    ]
    assert not stale, "rotate these and update the file: " + "; ".join(stale)
