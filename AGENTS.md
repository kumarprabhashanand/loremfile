# AGENTS.md — instructions for coding agents working in this repository

Read this before touching anything. `docs/15-implementation-plan.md` has the task order;
work through it, do not improvise a different plan.

## The four rules that outrank everything

1. **IMMUTABILITY.** Never change the bytes, `sha256`, byte count or MIME type at a
   published path. Ever. A fix is a **new path**, and the old manifest entry records
   `supersededBy`. CI and the R2 bucket lock rules both enforce this; a pull request that
   modifies an existing manifest entry cannot merge and a deploy that tries to overwrite
   an object fails the job.
2. **NEVER HAND-EDIT `manifest.json`** (or `sha256sums.txt`). Run
   `loremfile manifest update` **inside the toolchain container** and commit exactly what
   it writes. When CI reports different bytes for a media fixture, that is rule 3's
   exception, not a licence to edit: save the entries CI printed and run
   `loremfile manifest adopt --from <file>`.
3. **ALWAYS GENERATE INSIDE THE PINNED TOOLCHAIN IMAGE** (`tools/TOOLCHAIN_DIGEST`).
   Host output differs for media and images and will fail the lock check.
   **For media the image is necessary but not sufficient**: `libx264`, `libvpx` and
   `libopus` pick SIMD kernels from the CPU features they find, which no ffmpeg flag
   controls, so your machine and CI can legitimately disagree on a handful of fixtures
   (`docs/06` §4). **CI is the authority** — it builds the bytes the deploy uploads.
4. **NO CREDENTIALS ON ANY LOCAL MACHINE.** Every privileged operation runs through
   `deploy.yml` or `infra.yml` (modes `audit`, `apply`, `probe`, `restore`, `redact`).
   If a task seems to need a token locally, you have misread the task — check
   `docs/09-ci-cd.md` §3.2b.

## The commands

Everything runs inside the container:

```bash
docker pull "$(cat tools/TOOLCHAIN_DIGEST)"
docker run --rm -it -v "$PWD:/work" "$(cat tools/TOOLCHAIN_DIGEST)" bash
pip install -e .
```

| Command | Purpose |
|---|---|
| `loremfile catalog validate` | Schema and cross-checks on `catalog/*.yaml` |
| `loremfile build (--new \| --missing-in-bucket \| --all) [--only PATH…] [--format FMT…]` | Generate into `build/fixtures/` |
| `loremfile validate [--only PATH…] [--format FMT…]` | Run the validators on `build/fixtures/` |
| `loremfile manifest update \| check` | Update (you, in a PR) or verify (CI) the lock file |
| `loremfile site build \| site serve` | Render and preview the website |
| `loremfile verify-live --mode smoke\|daily\|full` | Contract checks against production — needs no credentials |

The full table is `docs/06-generation-pipeline.md` §10. Every command exits non-zero on
failure and supports `--json`.

## Placeholders

`<OWNER>` and the contact mailbox are placeholders until the owner answers Q-03 and Q-07
(`docs/18-open-questions.md`). They live in `src/loremfile/config.py`, the workflows,
`CODEOWNERS`, `security.txt` and `llms.txt`. Find them with:

```bash
grep -rn '<OWNER>' --exclude-dir=.git .
```

M1 and M3 can be built with the placeholders in place. M2 and M5 cannot.
`<CONTROLLER>`, `<CONTACT_EMAIL>` and `<DPA_ACCEPTED_DATE>` in `docs/13-legal-and-policy.md`
block M4.2 — do not invent values for them.

## Never

- Never commit secrets, tokens, or `.env` files. Secret scanning and push protection are on.
- Never commit generated binaries. `build/` is gitignored; fixtures live in R2 and in
  GitHub Release archives, not in git.
- Never add a dependency without regenerating `tools/requirements.lock` **and** bumping
  `tools/TOOLCHAIN_DIGEST` in the same pull request.
- Never skip tests to fit a session. Stop mid-milestone and write down where you stopped.
- Never decide anything `docs/18-open-questions.md` marks as an owner decision.
- Never publish or post anything publicly. The owner publishes launch posts.
- Never expand scope. The launch set is the 229 fixtures in `docs/05-fixture-catalog.md` §9,
  not all 417.

## Determinism

**Spike determinism on any unfamiliar format before writing its catalog entry.** Generate
twice under the guard and compare bytes. A nondeterministic fixture that reaches the
manifest is frozen there permanently — `sha256`, `bytes` and `mime` can never change at a
published path, so there is no later opportunity to fix it.

**Read the diff before committing, not the intention.** Every shape below is about
reasoning; this one is about whether the edit carried that reasoning into the repo, and it
is the layer where nothing else is watching. Two string-slice bugs in one session —
`s[s.index(a):s.index(b)]` where `a` occurs *after* `b`, yielding an empty slice and an
insertion at position 0 — were both plainly visible in the diff before they became test
failures, and one of them was followed by a restore that silently reverted good work
alongside the bad. `ruff` caught both because they happened to be syntactically invalid.

**Four shapes of assertion that is not assertable.** One family — a check that cannot
report the thing it names — but they present differently enough that a single rule misses
the rest. Each has its own detection question, and each was found the hard way. *(The
count said "three" for a while after the fourth row was added, in the section about
checks that do not check. Fixed 2026-09-10.)*

| Shape | Ask | Found in |
|---|---|---|
| **Passes on absence** — it compares or reports without requiring the subject to exist | *Would this still pass if the thing it inspects were not there at all?* | `url-normalization` comparing two absent CSPs as `"" == ""`; `404-caching` reporting `cf-cache-status` and passing on `DYNAMIC` |
| **Vacuously true over an empty set** — the same shape one level up, and the easiest to write by accident | *What builds the set? Can it come back empty, and would every assertion still hold?* | `test_workflow_commands.py`: every assertion in it is "for each `loremfile …` found in a workflow, the command exists" — all true of a search that finds nothing. A regex typo, a renamed directory or a parser change makes the suite pass while checking zero things |
| **Promoting a detail string** — the human version of the same shape: a value is *read out of* a passing check and written down as a result | *Did the check assert this, or merely print it?* | Run 1: `url-normalization` passing was read as evidence that normalization was on, when that check could pass on two absent headers. Run 2: both `HIT`s were written into the record as confirmed, when the checks that produced them only observed. **Both of us did this, on the same output, in the same week** — one reading it as an operator, one as its author. The check's own honesty is the only defence; a detail string is not a finding |
| **Cannot fire** — the check runs, matches nothing, and is indistinguishable from a passing one | *Have I watched it fail?* | the double-escaped `ghcr\\.io` pattern that matched no workflow; `python -O` stripping every `assert` in the probe |
| **Asserts something else** — it fails or passes on a fact adjacent to the one it names | *Could this fail for a reason other than the thing it names? If the named thing broke, would this fail?* | `www-redirect` following the redirect and asserting the apex root's honest 404; `rate-limit` concluding "the rule is not in effect" from load it never generated |

**The empty-set shape deserves its own habit, because it does not look like a bug.**
Whenever a test's claims are *universally quantified over a set it discovered* — a glob, a
regex sweep, a parse, a filter, a directory walk — the discovery is part of the assertion
and has to be asserted too. The rule: **a suite that says "everything found is valid" ships
with a control that something is found**, and that control names specifics rather than
counting (`assert len(x) > 0` passes on one accidental match; naming five commands you know
are there does not). Write that control first. It costs three lines, it fails immediately
if the finder is broken, and it is the only assertion in such a suite that is not vacuous
on an empty result.

The first is caught by driving the check against nothing. The second by the negative
control. The third only by reading each check and asking both questions — no sweep finds
it, which is why an audit of every check is worth doing after any of them appears. The
fourth has no automated defence at all: it is caught by a check that cannot report what
it did not assert, which is why the others matter.

**Every guard ships with a negative control that proves it fires.** A guard that cannot
fire is indistinguishable from a working one, and a green check is not evidence about it.
Introduce the violation deliberately and watch it fail. This is not hypothetical: the
workflow-digest guard's first pattern was double-escaped and matched nothing, and only its
control caught that — it would otherwise have passed forever while checking nothing.

This is not theoretical. `docs/06` §4 lists what each library does about randomness and
timestamps; one of those claims was simply wrong (fastavro draws its sync marker from a
compiled C extension, below the layer the determinism guard patches). The list is
assumption-shaped, and every entry carries a proving fixture and a verification date for
that reason.

## Verification discipline

Do not assert a vendor fact you have not checked in the current session. Every `[VERIFY]`
tag in `docs/08-infrastructure.md` §6 and `docs/19-cost-and-quotas.md` must be resolved by
calling the API or observing the behaviour, and the outcome written into the document **in
the same pull request**. If a document and reality disagree, fix the document in that same
pull request. Report failures with the actual output; never claim a step passed that you
did not run.

## Pull request checklist

- [ ] `loremfile catalog validate` passes inside the container
- [ ] Every new fixture has `description`, `tags`, `expect`, `size_class`
- [ ] Generator **plus** validator **plus** negative test **plus** determinism test, in this PR
- [ ] No third-party content, no real personal data, no private keys, no executables, no
      external entities (`docs/13-legal-and-policy.md` §5)
- [ ] I did not modify any existing manifest entry (immutability)
- [ ] `CHANGELOG.md` updated, listing every added path
- [ ] New format? `loremfile infra locks --write` run and the owner step noted in the description

## State lives in the repository

You have no memory between sessions. **Before ending any session**, update the
"Implementation status" issue with what you did, what is next, what is blocked and who
unblocks it, and any `[VERIFY]` you resolved together with its answer. Anything not written
down is lost.
