"""A weekly look at the AI crawlers nobody here has decided about yet (docs/09 §3.4).

This **never** edits a rule. It reads a public list of AI agents, subtracts the tokens the
edge and robots.txt already name and the ones already considered, and reports what is left
so the owner can decide. Blocking is a decision, and a decision is not a job for a cron.

Two failure modes are handled deliberately:

- **The fetch fails.** That is not a finding about crawlers, so the command says so and the
  workflow leaves the advisory issue exactly as it found it. A run that learned nothing must
  not close an issue (`11` §7.2).
- **The expression grows past what Cloudflare accepts.** A rule expression may be at most
  4,096 characters (Cloudflare's rules documentation), and every token added here lengthens
  one. Past the limit the rule cannot be created or updated at all, so the guard fails the
  run rather than letting the next `infra apply` discover it against the live zone.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Maintained at github.com/ai-robots-txt/ai.robots.txt: a list of AI agents with the
#: operator and purpose of each, which is why it is read rather than a vendor page.
KNOWN_AGENTS_URL = "https://raw.githubusercontent.com/ai-robots-txt/ai.robots.txt/main/robots.json"
#: Cloudflare: "The maximum length of a rule expression is 4,096 characters." A rule over
#: the limit "cannot be created or updated".
MAX_EXPRESSION_CHARACTERS = 4096
#: Names already weighed and not blocked. New entries in the list upstream are what the
#: watch is for; the ones that were there when it was written are not news.
SEEN_FILE = Path("infra") / "crawlers-seen.json"

TOKEN = re.compile(r'http\.user_agent contains "([^"]+)"')
ROBOTS_AGENT = re.compile(r"^User-agent: (.+)$", re.M)


class WatchError(RuntimeError):
    """The list could not be read."""


@dataclass(frozen=True)
class Agent:
    name: str
    operator: str
    function: str

    def render(self) -> str:
        return f"{self.name} — {self.operator}; {self.function}"


def blocked_tokens(root: Path) -> set[str]:
    """Every agent token this repository already names, at the edge or in robots.txt.

    Both, because either one is a decision already taken about that agent.
    """
    from loremfile.site.build import ROBOTS_TXT  # noqa: PLC0415 - avoids a cycle at import

    tokens = {agent.strip() for agent in ROBOTS_AGENT.findall(ROBOTS_TXT)} - {"*"}
    for path in sorted((root / "infra" / "rulesets").glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for rule in document.get("rules", []):
            tokens |= set(TOKEN.findall(str(rule.get("expression", ""))))
    return {token.lower() for token in tokens}


def seen_names(root: Path) -> set[str]:
    document = json.loads((root / SEEN_FILE).read_text(encoding="utf-8"))
    return {str(name).lower() for name in document["agents"]}


def fetch_known(url: str = KNOWN_AGENTS_URL, *, timeout: int = 30) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=timeout) as raw:  # noqa: S310 - fixed https
            document = json.loads(raw.read())
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise WatchError(f"could not read {url}: {exc}") from exc
    if not isinstance(document, dict) or not document:
        raise WatchError(f"{url} did not answer with a non-empty object")
    return document


def unreviewed(known: dict[str, Any], blocked: set[str], seen: set[str]) -> list[Agent]:
    """The agents in the list that are neither blocked here nor already considered."""
    decided = blocked | seen
    found = [
        Agent(
            name=name,
            operator=str((entry or {}).get("operator") or "operator not stated"),
            function=str((entry or {}).get("function") or "function not stated"),
        )
        for name, entry in known.items()
        if name.lower() not in decided
    ]
    return sorted(found, key=lambda agent: agent.name.lower())


def over_long_expressions(root: Path) -> list[str]:
    """Committed rules whose expression Cloudflare would refuse (over 4,096 characters)."""
    problems: list[str] = []
    for path in sorted((root / "infra" / "rulesets").glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for rule in document.get("rules", []):
            length = len(str(rule.get("expression", "")))
            if length > MAX_EXPRESSION_CHARACTERS:
                problems.append(
                    f"{path.stem}:{rule.get('ref')}: {length:,} characters, over "
                    f"{MAX_EXPRESSION_CHARACTERS:,} — Cloudflare refuses to create or update it"
                )
    return problems
