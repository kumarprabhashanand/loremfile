"""The two pages that name the operator (ADR-028, docs/13 §3b).

Values come only from the production environment and are never printed: every message here
is a count or a secret's name. Committed pages carry `%%IMPRINT_*%%` placeholders.
"""

from __future__ import annotations

import html
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from loremfile.site import routes

SECRETS = ("IMPRINT_NAME", "IMPRINT_STREET", "IMPRINT_POSTAL_CITY")
PLACEHOLDERS = {name: f"%%{name}%%" for name in SECRETS}


class LegalError(RuntimeError):
    """A legal value is missing, or a guard could not run."""


def values_from(env: Mapping[str, str]) -> dict[str, str]:
    missing = [name for name in SECRETS if not env.get(name, "").strip()]
    if missing:
        raise LegalError(
            f"missing or empty: {', '.join(missing)}. A blank Impressum breaches § 18 MStV, "
            "so nothing is built (docs/13 §3b)"
        )
    return {name: env[name].strip() for name in SECRETS}


def fill(site_dir: Path, values: Mapping[str, str]) -> int:
    """Write the values into exactly the two legal keys; returns the placeholders replaced."""
    replaced = 0
    for key in routes.LEGAL_KEYS:
        page = site_dir / routes.disk_path(key)
        text = page.read_text(encoding="utf-8")
        for name, placeholder in PLACEHOLDERS.items():
            replaced += text.count(placeholder)
            text = text.replace(placeholder, html.escape(values[name], quote=True))
        page.write_text(text, encoding="utf-8", newline="\n")
    return replaced


def leftover_placeholders(site_dir: Path) -> list[str]:
    """Keys still carrying a placeholder: publishing one would publish a blank Impressum."""
    tokens = [placeholder.encode() for placeholder in PLACEHOLDERS.values()]
    return [
        key
        for key, path in routes.site_files(site_dir).items()
        if any(token in path.read_bytes() for token in tokens)
    ]


def twins(site_dir: Path) -> list[str]:
    keys = routes.site_files(site_dir)
    return [key for key in routes.LEGAL_TWINS if key in keys]


@dataclass
class LegalReport:
    replaced: int = 0
    pages_missing_a_value: int = 0
    other_keys_with_a_value: int = 0
    twins: int = 0
    placeholders_left: int = 0
    values_in_git: int = 0

    @property
    def problems(self) -> list[str]:
        checks = (
            (self.pages_missing_a_value, "legal page(s) lack a value after filling"),
            (
                self.other_keys_with_a_value,
                "site key(s) other than legal/imprint and legal/privacy contain a legal value",
            ),
            (self.twins, "twin key(s) of the legal pages exist; the edge rules match exact paths"),
            (self.placeholders_left, "site key(s) still carry an %%IMPRINT_ placeholder"),
            (
                self.values_in_git,
                "legal value(s) are in the repository: remove them and open an incident "
                "(docs/13 §3b)",
            ),
        )
        return [f"{count} {what}" for count, what in checks if count]

    def render(self) -> str:
        return (
            f"  legal: {self.replaced} placeholder(s) filled; other keys with a value "
            f"{self.other_keys_with_a_value}; twins {self.twins}; placeholders left "
            f"{self.placeholders_left}; values in git {self.values_in_git}"
        )


def audit(
    site_dir: Path, values: Mapping[str, str], *, in_git: Callable[[str], bool]
) -> LegalReport:
    """The count-only checks of docs/15 M4.1, run after `fill`."""
    report = LegalReport()
    files = routes.site_files(site_dir)
    escaped = [html.escape(value, quote=True).encode() for value in values.values()]
    forms = {form for value in values.values() for form in (value.encode(), *escaped)}
    for key, path in files.items():
        body = path.read_bytes()
        if key in routes.LEGAL_KEYS:
            report.pages_missing_a_value += not all(value in body for value in escaped)
        elif any(form in body for form in forms):
            report.other_keys_with_a_value += 1
    report.pages_missing_a_value += sum(key not in files for key in routes.LEGAL_KEYS)
    report.twins = len(twins(site_dir))
    report.placeholders_left = len(leftover_placeholders(site_dir))
    report.values_in_git = sum(in_git(value) for value in values.values())
    return report


def in_repository(value: str, *, cwd: Path) -> bool:
    """`git grep -qF` for one value; the value is an argument, never output (docs/13 §3b)."""
    executable = shutil.which("git")
    if executable is None:
        raise LegalError("git is not on PATH")
    done = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [executable, "grep", "-qF", "-e", value], cwd=cwd, capture_output=True, check=False
    )
    if done.returncode in {0, 1}:
        return done.returncode == 0
    raise LegalError(f"git grep failed (exit {done.returncode})")
