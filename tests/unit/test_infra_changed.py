"""`deploy.yml` applies `infra/` when it changed since the zone last converged (ADR-029).

Not since `HEAD~1`. The concurrency group keeps one pending run and a newer arrival replaces
it, so a replaced deploy's commit is never deployed by its own run; an `infra/` change in it
was invisible from the next commit and never applied. The base is now the head of the most
recent successful push run on main, other than the run asking — and each way of getting that
wrong is pinned here: a run that proves nothing taken as proof, the asking run taken as its
own base, a lookup that failed read as an answer in either direction.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from click.testing import CliRunner

from loremfile import cli
from loremfile.infra import changed
from loremfile.infra.changed import Base, Undecided, changed_paths, decide, parse_pages, select_base

DEPLOY = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy.yml"
CURRENT = 9_000_000


def run(number: int, sha: str, **overrides: Any) -> dict[str, Any]:
    """A deploy.yml run as the API lists it: a successful push to main unless overridden.

    `sha` is one hex digit, repeated, or a full SHA from a real repository."""
    return {
        "id": 1_000 + number,
        "run_number": number,
        "event": "push",
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
        "head_sha": sha if len(sha) == 40 else sha * 40,
    } | overrides


# --- which run is the base ----------------------------------------------------


def test_a_successful_push_run_on_main_is_the_base() -> None:
    """Control first. Every skip test below asserts that some run is *not* chosen, and a
    selector that never chose anything would pass all of them."""
    assert select_base([run(5, "a")], exclude_run=CURRENT) == Base(1005, "a" * 40)


SKIPPED = {
    "cancelled": {"conclusion": "cancelled"},
    "failed": {"conclusion": "failure"},
    "workflow_dispatch": {"event": "workflow_dispatch"},
    "still running": {"status": "in_progress", "conclusion": None},
    "another branch": {"head_branch": "feature"},
}


@pytest.mark.parametrize("variant", list(SKIPPED.values()), ids=list(SKIPPED))
def test_a_run_that_proves_nothing_is_skipped(variant: dict[str, Any]) -> None:
    newer, older = run(7, "b", **variant), run(6, "a")
    assert select_base([newer, older], exclude_run=CURRENT) == Base(1006, "a" * 40)
    assert select_base([newer], exclude_run=CURRENT) is None
    # Negative control: the same run without the variant is chosen, so it was the variant —
    # not the run number or the list order — that excluded it.
    assert select_base([run(7, "b"), older], exclude_run=CURRENT) == Base(1007, "b" * 40)


def test_the_current_run_is_never_its_own_base() -> None:
    """Shaped as a re-run of a run that had already succeeded, which the API lists as
    completed and successful. Chosen, it would diff the commit against itself: unchanged,
    always."""
    current, older = run(8, "c", id=CURRENT), run(7, "b")
    assert select_base([current, older], exclude_run=CURRENT) == Base(1007, "b" * 40)
    # Negative control: excluding some other id, the same list does choose it.
    assert select_base([current, older], exclude_run=1) == Base(CURRENT, "c" * 40)


def test_the_most_recent_is_the_highest_run_number_not_the_first_listed() -> None:
    runs = [run(3, "a"), run(9, "c"), run(5, "b")]
    assert select_base(runs, exclude_run=CURRENT) == Base(1009, "c" * 40)


def test_no_runs_at_all_is_none() -> None:
    assert select_base([], exclude_run=CURRENT) is None


@pytest.mark.parametrize("field", [*changed.SHAPE, "conclusion"])
def test_a_run_list_whose_shape_changed_is_undecided_not_empty(field: str) -> None:
    """The dangerous misreading: a renamed field makes every run look unqualified, which is
    "no successful run", which means apply. It has to fail instead — including on a run that
    would have been skipped anyway, and when a usable base is also in the list."""
    broken = run(4, "a")
    del broken[field]
    with pytest.raises(Undecided, match=field):
        select_base([broken], exclude_run=CURRENT)

    cancelled = run(5, "b", conclusion="cancelled")
    del cancelled[field]
    with pytest.raises(Undecided, match=field):
        select_base([cancelled, run(3, "c")], exclude_run=CURRENT)


def test_a_base_without_a_full_sha_is_undecided() -> None:
    with pytest.raises(Undecided, match="head SHA"):
        select_base([run(4, "a", head_sha="abc123")], exclude_run=CURRENT)


# --- reading gh's output --------------------------------------------------------


def page(*runs: dict[str, Any], total: int | None = None) -> str:
    count = len(runs) if total is None else total
    return json.dumps({"total_count": count, "workflow_runs": list(runs)})


def test_pages_are_read_one_after_another() -> None:
    """`gh api --paginate` writes `{…}{…}` with nothing between the pages — observed on this
    repository's deploy.yml runs on 2026-09-15 — which a single json.loads rejects."""
    text = page(run(9, "c"), run(8, "b"), total=3) + page(run(7, "a"), total=3)
    with pytest.raises(json.JSONDecodeError):
        json.loads(text)
    assert [r["run_number"] for r in parse_pages(text)] == [9, 8, 7]


def test_an_empty_page_is_an_answer_and_no_page_is_not() -> None:
    assert parse_pages(page()) == []
    for nothing in ("", "  \n"):
        with pytest.raises(Undecided, match="no page"):
            parse_pages(nothing)


@pytest.mark.parametrize("text", ["<html>rate limited</html>", '{"message": "Not Found"}', "[]"])
def test_output_that_is_not_a_run_list_is_undecided(text: str) -> None:
    with pytest.raises(Undecided):
        parse_pages(text)


class _Gh:
    """Replaces `subprocess.run` for one test and records every argv, in one list."""

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, *, stdout: str = "", code: int = 0, stderr: str = ""
    ) -> None:
        self.calls: list[list[str]] = []
        self.result = (code, stdout, stderr)
        monkeypatch.setattr(changed.shutil, "which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr(changed.subprocess, "run", self._run)

    def _run(self, argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        code, stdout, stderr = self.result
        return subprocess.CompletedProcess(argv, code, stdout=stdout, stderr=stderr)


def test_the_lookup_names_the_repository_and_reads_every_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gh = _Gh(monkeypatch, stdout=page(run(2, "a")))
    assert len(changed.fetch_runs("owner/loremfile")) == 1
    (argv,) = gh.calls
    assert argv[:3] == ["/usr/bin/gh", "api", "--paginate"]
    endpoint = argv[3]
    assert endpoint.startswith("repos/owner/loremfile/actions/workflows/deploy.yml/runs?")
    assert "event=push" in endpoint
    assert "branch=main" in endpoint


def test_a_failed_lookup_is_undecided_and_says_why(monkeypatch: pytest.MonkeyPatch) -> None:
    _Gh(monkeypatch, code=1, stderr="HTTP 502: Bad Gateway")
    with pytest.raises(Undecided, match="502"):
        changed.fetch_runs("owner/loremfile")


def test_no_repository_is_undecided_before_anything_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    gh = _Gh(monkeypatch, stdout=page())
    with pytest.raises(Undecided, match="OWNER/REPO"):
        changed.fetch_runs("")
    assert gh.calls == []


# --- the diff, against a real repository ------------------------------------------


def git(repo: Path, *args: str) -> str:
    executable = shutil.which("git")
    assert executable is not None
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            executable,
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            *args,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def history(tmp_path: Path) -> dict[str, Any]:
    """deployed → replaced (changes infra/; its deploy was replaced while pending) → head
    (touches nothing in infra/). The history ADR-029's leftover risk describes."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    shas: dict[str, Any] = {"repo": repo}
    for name, path, content in (
        ("deployed", "infra/zone-settings.json", '{"ssl": "strict"}\n'),
        ("replaced", "infra/zone-settings.json", '{"ssl": "strict", "tls_1_3": "zrt"}\n'),
        ("head", "README.md", "unrelated\n"),
    ):
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(content, encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", name)
        shas[name] = git(repo, "rev-parse", "HEAD")
    return shas


def serve(monkeypatch: pytest.MonkeyPatch, runs: list[dict[str, Any]] | Exception) -> None:
    def fetch(_repository: str) -> list[dict[str, Any]]:
        if isinstance(runs, Exception):
            raise runs
        return runs

    monkeypatch.setattr(changed, "fetch_runs", fetch)


def test_head_1_cannot_see_a_change_made_in_a_replaced_deploy(history: dict[str, Any]) -> None:
    """The defect, replayed: `HEAD~1` is the replaced commit, so the diff from it is empty."""
    repo = history["repo"]
    assert changed_paths("HEAD~1", history["head"], cwd=repo) == []
    assert changed_paths(history["deployed"], history["head"], cwd=repo) == [
        "infra/zone-settings.json"
    ]


def test_the_last_successful_deploy_is_the_base_and_finds_the_change(
    monkeypatch: pytest.MonkeyPatch, history: dict[str, Any]
) -> None:
    serve(
        monkeypatch,
        [run(12, history["replaced"], conclusion="cancelled"), run(11, history["deployed"])],
    )
    decision = decide(
        repository="owner/loremfile", exclude_run=CURRENT, head=history["head"], cwd=history["repo"]
    )
    assert decision.changed is True
    assert "infra/zone-settings.json" in decision.reason


def test_it_can_also_say_unchanged(
    monkeypatch: pytest.MonkeyPatch, history: dict[str, Any]
) -> None:
    """Negative control: a `decide` that always said changed would pass the test above — and
    would be "apply on every deploy", which ADR-029 rejects."""
    serve(monkeypatch, [run(12, history["replaced"]), run(11, history["deployed"])])
    decision = decide(
        repository="owner/loremfile", exclude_run=CURRENT, head=history["head"], cwd=history["repo"]
    )
    assert decision.changed is False


def test_no_successful_push_run_means_changed(
    monkeypatch: pytest.MonkeyPatch, history: dict[str, Any]
) -> None:
    serve(monkeypatch, [run(3, history["deployed"], event="workflow_dispatch")])
    decision = decide(
        repository="owner/loremfile", exclude_run=CURRENT, head=history["head"], cwd=history["repo"]
    )
    assert decision.changed is True
    assert "no earlier successful" in decision.reason


def test_a_base_this_checkout_does_not_have_is_undecided(
    monkeypatch: pytest.MonkeyPatch, history: dict[str, Any]
) -> None:
    serve(monkeypatch, [run(11, "d")])
    with pytest.raises(Undecided, match="not a commit"):
        decide(
            repository="owner/loremfile",
            exclude_run=CURRENT,
            head=history["head"],
            cwd=history["repo"],
        )


def test_deploying_a_commit_older_than_the_base_is_undecided(
    monkeypatch: pytest.MonkeyPatch, history: dict[str, Any]
) -> None:
    """A re-run of an old deploy after a newer one succeeded. The diff would describe going
    backwards, and applying on it would put an older infra/ on the zone."""
    serve(monkeypatch, [run(12, history["head"])])
    with pytest.raises(Undecided, match="not an ancestor"):
        decide(
            repository="owner/loremfile",
            exclude_run=CURRENT,
            head=history["deployed"],
            cwd=history["repo"],
        )


# --- the command and the workflow ------------------------------------------------


def invoke(
    monkeypatch: pytest.MonkeyPatch,
    history: dict[str, Any],
    runs: list[dict[str, Any]] | Exception,
) -> Any:
    serve(monkeypatch, runs)
    monkeypatch.chdir(history["repo"])
    arguments = ["infra", "changed", "--exclude-run", str(CURRENT), "--head", history["head"]]
    return CliRunner().invoke(cli.main, [*arguments, "--repository", "owner/loremfile"])


def test_the_command_prints_one_verdict_line_on_stdout(
    monkeypatch: pytest.MonkeyPatch, history: dict[str, Any]
) -> None:
    """Stdout is appended to $GITHUB_OUTPUT, so it holds the verdict and nothing else."""
    result = invoke(monkeypatch, history, [run(11, history["deployed"])])
    assert result.exit_code == 0, result.output
    assert result.stdout == "changed=true\n"
    assert "infra/zone-settings.json" in result.stderr


def test_a_command_that_cannot_tell_prints_no_verdict_and_fails(
    monkeypatch: pytest.MonkeyPatch, history: dict[str, Any]
) -> None:
    """An unset `changed` reads as unchanged in the `if:` that gates the apply — a guess. So
    the step fails instead. The test above is the control: the verdict does get printed."""
    result = invoke(monkeypatch, history, Undecided("gh api …/runs failed: HTTP 502"))
    assert result.exit_code == 1
    assert "changed=" not in result.stdout
    assert "502" in result.stderr


def test_deploy_asks_the_command_instead_of_diffing_head_1() -> None:
    document = yaml.safe_load(DEPLOY.read_text(encoding="utf-8"))
    found = [s for s in document["jobs"]["deploy"]["steps"] if s.get("id") == "infra_changed"]
    assert len(found) == 1, "deploy.yml has no single infra_changed step"
    (step,) = found
    script = step["run"]
    assert 'loremfile infra changed --exclude-run "$GITHUB_RUN_ID" --head "$GITHUB_SHA"' in script
    assert '>> "$GITHUB_OUTPUT"' in script
    assert step["env"]["GH_TOKEN"] == "${{ github.token }}"  # noqa: S105 - an expression
    assert document["permissions"]["actions"] == "read", "listing runs needs actions: read"
    for stale in ("HEAD~1", "event.before", "|| true"):
        assert stale not in script, stale


def test_that_step_is_what_gates_the_apply() -> None:
    steps = yaml.safe_load(DEPLOY.read_text(encoding="utf-8"))["jobs"]["deploy"]["steps"]
    (apply,) = [s for s in steps if s.get("run", "").strip() == "loremfile infra apply"]
    assert "steps.infra_changed.outputs.changed == 'true'" in apply["if"]
    order = [s.get("id") or s.get("name") for s in steps]
    assert order.index("infra_changed") < order.index(apply["name"])
