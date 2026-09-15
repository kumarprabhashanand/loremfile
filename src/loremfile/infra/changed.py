"""Did `infra/` change since the zone last converged? (ADR-029)

`deploy.yml` applies `infra/` only when it changed, and "changed" used to mean "changed in
this commit": a `HEAD~1..HEAD` diff. That misses a deploy that never ran. The zone's
concurrency group keeps one run pending and a newer arrival replaces it, so a replaced run's
commit is never deployed by its own run — and if that commit changed `infra/` and the next
one did not, the change was never applied.

So the base is the commit the zone last converged to: the head SHA of the most recent
`deploy.yml` run that was a **push** to **main** and **succeeded**, other than the run
asking. A cancelled or failed run is no evidence that its commit reached the zone, and a
dispatch may have been a dry run. With no such run at all, `infra/` counts as changed.

**Never a guess in either direction.** A run list that cannot be fetched or read, a base
missing from the checkout, or a base that is not an ancestor of the commit being deployed
raises `Undecided`, and the step fails. "Could not tell" read as unchanged skips an apply
that was needed; read as changed, it applies on every broken lookup — and an apply is not
free: it converges `security_level`, which switches off an operator's Under Attack Mode
(`docs/11` §7.4). Applying on every deploy was rejected for the same reason.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WORKFLOW = "deploy.yml"
BRANCH = "main"
EVENT = "push"
WATCHED = "infra/"

#: The fields selection reads, and the type each must have. Checked on every run in the
#: list, not only on the ones that qualify: a renamed field would otherwise make every run
#: look unqualified, and "no successful run" means apply.
SHAPE: dict[str, type] = {
    "id": int,
    "run_number": int,
    "event": str,
    "head_branch": str,
    "status": str,
    "head_sha": str,
}
FULL_SHA = re.compile(r"[0-9a-f]{40}")


class Undecided(RuntimeError):
    """Whether `infra/` changed could not be determined. Never read as either answer."""


@dataclass(frozen=True)
class Base:
    run_id: int
    sha: str


@dataclass(frozen=True)
class Decision:
    changed: bool
    reason: str


def _checked(run: object) -> Mapping[str, Any]:
    if not isinstance(run, Mapping):
        raise Undecided(f"a workflow run is not an object: {run!r}")
    for key, kind in SHAPE.items():
        value = run.get(key)
        if isinstance(value, bool) or not isinstance(value, kind):
            raise Undecided(f"workflow run {run.get('id', '?')} has no usable {key!r}: {value!r}")
    if "conclusion" not in run or not (
        run["conclusion"] is None or isinstance(run["conclusion"], str)
    ):
        raise Undecided(f"workflow run {run['id']} has no usable 'conclusion'")
    return run


def select_base(runs: Iterable[object], *, exclude_run: int) -> Base | None:
    """The run the zone last converged to, or None when no run qualifies.

    Qualifies: a push to main that completed with `success`, and is not `exclude_run`. The
    most recent is the highest `run_number` — not whichever the API happened to list first.
    """
    qualifying = [
        run
        for run in map(_checked, runs)
        if run["event"] == EVENT
        and run["head_branch"] == BRANCH
        and run["status"] == "completed"
        and run["conclusion"] == "success"
        and run["id"] != exclude_run
    ]
    if not qualifying:
        return None
    latest = max(qualifying, key=lambda run: int(run["run_number"]))
    if not FULL_SHA.fullmatch(latest["head_sha"]):
        raise Undecided(f"run {latest['id']} has no full head SHA: {latest['head_sha']!r}")
    return Base(run_id=latest["id"], sha=latest["head_sha"])


def parse_pages(text: str) -> list[object]:
    """Every run in `gh api --paginate` output.

    gh writes the pages one after another with nothing between them (`{…}{…}`), so values
    are decoded one at a time. **No page at all is an error, not an empty list**: an API
    answer with no runs is still a page, `{"total_count": 0, "workflow_runs": []}`.
    """
    decoder = json.JSONDecoder()
    runs: list[object] = []
    pages = 0
    index = 0
    while True:
        while index < len(text) and text[index].isspace():
            index += 1
        if index == len(text):
            break
        try:
            page, index = decoder.raw_decode(text, index)
        except ValueError as exc:
            raise Undecided(f"the run list is not JSON at offset {index}: {exc}") from exc
        if not isinstance(page, dict) or not isinstance(page.get("workflow_runs"), list):
            raise Undecided("a page of the run list has no `workflow_runs` array")
        runs.extend(page["workflow_runs"])
        pages += 1
    if pages == 0:
        raise Undecided("gh returned no page at all; even an empty run list is a page")
    return runs


def fetch_runs(repository: str) -> list[object]:
    """The push runs of `deploy.yml` on main, every page of them.

    The query narrows by event and branch; `select_base` checks both again, so an API that
    ignored a filter could not change the answer. The repository is named in the path rather
    than inferred from the checkout, for the reason `gh_issue` records.
    """
    if repository.count("/") != 1:
        raise Undecided(f"no OWNER/REPO to look runs up in (got {repository!r})")
    executable = shutil.which("gh")
    if executable is None:
        raise Undecided("gh is not on PATH; it lives in the toolchain image")
    endpoint = (
        f"repos/{repository}/actions/workflows/{WORKFLOW}/runs"
        f"?branch={BRANCH}&event={EVENT}&per_page=100&exclude_pull_requests=true"
    )
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [executable, "api", "--paginate", endpoint],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise Undecided(f"gh api timed out after {exc.timeout}s") from exc
    if completed.returncode != 0:
        raise Undecided(f"gh api {endpoint} failed: {completed.stderr.strip()}")
    return parse_pages(completed.stdout)


def _git(args: list[str], cwd: Path | None) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("git")
    if executable is None:
        raise Undecided("git is not on PATH")
    try:
        return subprocess.run(  # noqa: S603 - fixed argv, no shell
            [executable, *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise Undecided(f"git {args[0]} timed out after {exc.timeout}s") from exc


def changed_paths(base: str, head: str, *, cwd: Path | None = None) -> list[str]:
    """Paths under `infra/` that differ from `base` to `head`; raises when git cannot say."""
    for commit in (base, head):
        if _git(["cat-file", "-e", f"{commit}^{{commit}}"], cwd).returncode != 0:
            raise Undecided(
                f"{commit} is not a commit in this checkout (deploy.yml checks out with "
                "fetch-depth: 0, so this is not a shallow clone)"
            )
    ancestry = _git(["merge-base", "--is-ancestor", base, head], cwd)
    if ancestry.returncode == 1:
        raise Undecided(
            f"{base} is not an ancestor of {head}: the commit being deployed is not newer than "
            "the last successful deploy (a re-run of an older deploy?), so a diff would "
            "describe going backwards"
        )
    if ancestry.returncode != 0:
        raise Undecided(f"git merge-base failed: {ancestry.stderr.strip()}")
    diff = _git(["diff", "--name-only", base, head, "--", WATCHED], cwd)
    if diff.returncode != 0:
        raise Undecided(f"git diff failed: {diff.stderr.strip()}")
    return [line for line in diff.stdout.splitlines() if line]


def decide(
    *, repository: str, exclude_run: int, head: str = "HEAD", cwd: Path | None = None
) -> Decision:
    """Whether `deploy.yml` should apply `infra/`, and why. Raises `Undecided`."""
    base = select_base(fetch_runs(repository), exclude_run=exclude_run)
    if base is None:
        return Decision(
            changed=True,
            reason=f"no earlier successful push run of {WORKFLOW} on {BRANCH}; "
            "treating infra/ as changed",
        )
    paths = changed_paths(base.sha, head, cwd=cwd)
    since = f"{base.sha[:12]} (run {base.run_id}, the last successful push deploy)"
    if paths:
        return Decision(changed=True, reason=f"infra/ changed since {since}: {', '.join(paths)}")
    return Decision(changed=False, reason=f"infra/ unchanged since {since}")
