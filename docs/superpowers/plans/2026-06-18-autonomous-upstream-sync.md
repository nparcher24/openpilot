# Autonomous Upstream Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A scheduled GitHub Action that fast-forwards `master` from sunnypilot upstream, rebases the `ndm:` commits onto it, verifies the result builds the way the device builds it, and force-pushes `ndm-dev` only when every safety gate is green — otherwise opens a PR and pings the owner.

**Architecture:** The git mechanics, report schema, and gate decision live in a testable Python package `tools/ndm/` (invoked as `python -m openpilot.tools.ndm.sync`). A thin GitHub Actions workflow (`.github/workflows/ndm-sync.yaml`) orchestrates: it calls the `prepare` subcommand, runs Claude (`claude-code-action`) to resolve any rebase conflicts and perform a semantic review (writing `sync-report.json`), triggers upstream's existing `tests.yaml` against the trial branch as the build gate, then calls the `gate` subcommand to decide between `publish` (force-push `ndm-dev`) and `escalate` (open a PR).

**Tech Stack:** Python 3 (stdlib only — `subprocess`, `json`, `dataclasses`, `argparse`), pytest (repo standard, `-n auto`), GitHub Actions, `anthropics/claude-code-action`, `gh` CLI, `actionlint` for workflow linting.

## Global Constraints

- **Integration strategy: rebase**, never merge. The trial branch is `sync/<YYYY-MM-DD>`; the published branch is `ndm-dev`.
- **`ndm-dev` is mutated ONLY at the final publish step.** No earlier stage may touch it. Every failure path leaves `ndm-dev` exactly as it was.
- **`master` is only ever fast-forwarded.** If it cannot fast-forward to `upstream/master`, escalate — never force or rewrite `master`.
- **Force-push to `ndm-dev` is safe** for the device (the on-device updater hard-resets to the remote branch); rebasing is therefore acceptable.
- **Publish gate — force-push `ndm-dev` IFF ALL hold:** CI required jobs green **and** rebase status ∈ {`clean`, `resolved`} **and** report confidence == `high` **and** zero blocking flags (including submodule bumps). Anything else → escalate.
- **Fork submodules = `["opendbc"]`.** v1 detects an upstream bump of these and treats it as a blocking flag (notify-only); it does NOT auto-rebase the fork.
- **Claude auth in CI:** `CLAUDE_CODE_OAUTH_TOKEN` secret (owner's Claude Max subscription, no API billing).
- **Imports:** use the `openpilot.` package prefix, e.g. `from openpilot.tools.ndm.report import SyncReport`.
- **Tests:** `test_*.py`, co-located in `tools/ndm/`, stdlib + pytest only. Run with `pytest tools/ndm/ -v`.
- **Upstream URL:** `https://github.com/sunnypilot/sunnypilot.git`.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `tools/ndm/__init__.py` | Package marker. |
| `tools/ndm/report.py` | `SyncReport`/`Flag` dataclasses + `parse_report()` strict validation of `sync-report.json`. |
| `tools/ndm/gate.py` | Pure `decide()` — maps (CI result, report, bumps) → `"publish"`/`"escalate"`. |
| `tools/ndm/submodules.py` | `detect_bumps()` (pure) + `read_submodule_shas()` (git wrapper). |
| `tools/ndm/gitops.py` | git mechanics: `git()` helper, `add_upstream()`, `fast_forward_master()`, `create_trial_branch()`, `rebase_tweaks()`, `force_publish()`. |
| `tools/ndm/sync.py` | CLI: `prepare` / `gate` / `publish` subcommands wiring the above; reads/writes `sync-state.json` and emits `$GITHUB_OUTPUT` lines. |
| `tools/ndm/sync-prompt.md` | Claude instructions: resolve conflicts honoring `ndm:` intent, semantic review, and the exact `sync-report.json` / `sync-report.md` output contract. |
| `tools/ndm/test_report.py` | Tests for report parsing/validation. |
| `tools/ndm/test_gate.py` | Tests for the gate decision matrix. |
| `tools/ndm/test_submodules.py` | Tests for bump detection. |
| `tools/ndm/test_gitops.py` | Integration tests against temporary git repos. |
| `tools/ndm/test_prompt_contract.py` | Asserts the JSON example embedded in `sync-prompt.md` parses via `parse_report` (keeps prompt and schema in lockstep). |
| `.github/workflows/ndm-sync.yaml` | Scheduled/dispatch orchestrator. |
| `docs/ndm/upstream-sync.md` | Setup + operation runbook (secret, schedule, dry-run, escalation handling). |

---

## Task 1: Report schema + validation

**Files:**
- Create: `tools/ndm/__init__.py`
- Create: `tools/ndm/report.py`
- Test: `tools/ndm/test_report.py`

**Interfaces:**
- Produces: `Flag(type: str, file: str, detail: str)` dataclass; `SyncReport(status: str, confidence: str, summary: str, flags: list[Flag])` dataclass with `.to_json() -> str`; `parse_report(text: str) -> SyncReport`; `ReportError(ValueError)`. Valid `status` ∈ {`clean`,`resolved`,`risky`}; valid `confidence` ∈ {`high`,`low`}.

- [ ] **Step 1: Create the package marker**

Create `tools/ndm/__init__.py` (empty file).

- [ ] **Step 2: Write the failing tests**

Create `tools/ndm/test_report.py`:

```python
import pytest

from openpilot.tools.ndm.report import Flag, SyncReport, parse_report, ReportError


def test_parse_minimal_clean_report():
    report = parse_report('{"status": "clean", "confidence": "high", "summary": "ok"}')
    assert report.status == "clean"
    assert report.confidence == "high"
    assert report.summary == "ok"
    assert report.flags == []


def test_parse_report_with_flags():
    text = (
        '{"status": "resolved", "confidence": "high", "summary": "done",'
        ' "flags": [{"type": "semantic", "file": "a.py", "detail": "api moved"}]}'
    )
    report = parse_report(text)
    assert report.flags == [Flag(type="semantic", file="a.py", detail="api moved")]


def test_round_trip_to_json():
    report = SyncReport(status="risky", confidence="low", summary="hmm", flags=[])
    assert parse_report(report.to_json()) == report


def test_invalid_json_raises():
    with pytest.raises(ReportError):
        parse_report("not json")


def test_unknown_status_raises():
    with pytest.raises(ReportError):
        parse_report('{"status": "weird", "confidence": "high", "summary": "x"}')


def test_unknown_confidence_raises():
    with pytest.raises(ReportError):
        parse_report('{"status": "clean", "confidence": "maybe", "summary": "x"}')


def test_missing_field_raises():
    with pytest.raises(ReportError):
        parse_report('{"status": "clean", "summary": "x"}')


def test_malformed_flag_raises():
    with pytest.raises(ReportError):
        parse_report('{"status": "clean", "confidence": "high", "summary": "x",'
                     ' "flags": [{"type": "semantic"}]}')
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tools/ndm/test_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'openpilot.tools.ndm.report'`.

- [ ] **Step 4: Implement `report.py`**

Create `tools/ndm/report.py`:

```python
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

VALID_STATUS = {"clean", "resolved", "risky"}
VALID_CONFIDENCE = {"high", "low"}


class ReportError(ValueError):
  """Raised when sync-report.json is missing, malformed, or out of contract."""


@dataclass
class Flag:
  type: str
  file: str
  detail: str


@dataclass
class SyncReport:
  status: str
  confidence: str
  summary: str
  flags: list[Flag] = field(default_factory=list)

  def to_json(self) -> str:
    return json.dumps(asdict(self), indent=2)


def parse_report(text: str) -> SyncReport:
  try:
    data = json.loads(text)
  except json.JSONDecodeError as e:
    raise ReportError(f"sync-report.json is not valid JSON: {e}") from e

  for key in ("status", "confidence", "summary"):
    if key not in data:
      raise ReportError(f"missing required field: {key}")
  if data["status"] not in VALID_STATUS:
    raise ReportError(f"invalid status: {data['status']!r}")
  if data["confidence"] not in VALID_CONFIDENCE:
    raise ReportError(f"invalid confidence: {data['confidence']!r}")

  flags = []
  for f in data.get("flags", []):
    if not all(k in f for k in ("type", "file", "detail")):
      raise ReportError(f"flag missing required keys: {f}")
    flags.append(Flag(type=f["type"], file=f["file"], detail=f["detail"]))

  return SyncReport(
    status=data["status"],
    confidence=data["confidence"],
    summary=data["summary"],
    flags=flags,
  )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tools/ndm/test_report.py -v`
Expected: PASS (8 passed).

- [ ] **Step 6: Commit**

```bash
git add tools/ndm/__init__.py tools/ndm/report.py tools/ndm/test_report.py
git commit -m "ndm: sync-report schema + strict validation"
```

---

## Task 2: Gate decision

**Files:**
- Create: `tools/ndm/gate.py`
- Test: `tools/ndm/test_gate.py`

**Interfaces:**
- Consumes: `SyncReport` from `report.py`.
- Produces: `decide(*, ci_passed: bool, report: SyncReport, submodule_bumps: list[str]) -> str` returning `"publish"` or `"escalate"`.

- [ ] **Step 1: Write the failing tests**

Create `tools/ndm/test_gate.py`:

```python
from openpilot.tools.ndm.gate import decide
from openpilot.tools.ndm.report import Flag, SyncReport


def _ok_report():
  return SyncReport(status="clean", confidence="high", summary="ok", flags=[])


def test_publishes_when_everything_green():
  assert decide(ci_passed=True, report=_ok_report(), submodule_bumps=[]) == "publish"


def test_publishes_on_resolved_high_confidence():
  report = SyncReport(status="resolved", confidence="high", summary="ok", flags=[])
  assert decide(ci_passed=True, report=report, submodule_bumps=[]) == "publish"


def test_escalates_when_ci_fails():
  assert decide(ci_passed=False, report=_ok_report(), submodule_bumps=[]) == "escalate"


def test_escalates_on_submodule_bump():
  assert decide(ci_passed=True, report=_ok_report(), submodule_bumps=["opendbc"]) == "escalate"


def test_escalates_on_risky_status():
  report = SyncReport(status="risky", confidence="high", summary="x", flags=[])
  assert decide(ci_passed=True, report=report, submodule_bumps=[]) == "escalate"


def test_escalates_on_low_confidence():
  report = SyncReport(status="resolved", confidence="low", summary="x", flags=[])
  assert decide(ci_passed=True, report=report, submodule_bumps=[]) == "escalate"


def test_escalates_when_flags_present():
  report = SyncReport(status="clean", confidence="high", summary="x",
                      flags=[Flag(type="semantic", file="a.py", detail="api moved")])
  assert decide(ci_passed=True, report=report, submodule_bumps=[]) == "escalate"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tools/ndm/test_gate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'openpilot.tools.ndm.gate'`.

- [ ] **Step 3: Implement `gate.py`**

Create `tools/ndm/gate.py`:

```python
from __future__ import annotations

from openpilot.tools.ndm.report import SyncReport

PUBLISHABLE_STATUS = {"clean", "resolved"}


def decide(*, ci_passed: bool, report: SyncReport, submodule_bumps: list[str]) -> str:
  """Return 'publish' only when every safety gate is satisfied, else 'escalate'."""
  if not ci_passed:
    return "escalate"
  if submodule_bumps:
    return "escalate"
  if report.status not in PUBLISHABLE_STATUS:
    return "escalate"
  if report.confidence != "high":
    return "escalate"
  if report.flags:
    return "escalate"
  return "publish"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tools/ndm/test_gate.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add tools/ndm/gate.py tools/ndm/test_gate.py
git commit -m "ndm: publish/escalate gate decision"
```

---

## Task 3: Submodule bump detection

**Files:**
- Create: `tools/ndm/submodules.py`
- Test: `tools/ndm/test_submodules.py`

**Interfaces:**
- Produces: `detect_bumps(old_shas: dict[str, str], new_shas: dict[str, str], fork_paths: list[str]) -> list[str]` (pure); `read_submodule_shas(repo: str, ref: str, paths: list[str]) -> dict[str, str]` (git wrapper, used by `sync.py`); `FORK_SUBMODULES = ["opendbc"]`.

- [ ] **Step 1: Write the failing tests**

Create `tools/ndm/test_submodules.py`:

```python
from openpilot.tools.ndm.submodules import FORK_SUBMODULES, detect_bumps


def test_no_bump_when_shas_match():
  old = {"opendbc": "aaa", "panda": "bbb"}
  new = {"opendbc": "aaa", "panda": "ccc"}
  assert detect_bumps(old, new, ["opendbc"]) == []


def test_detects_bump_of_fork_path():
  old = {"opendbc": "aaa"}
  new = {"opendbc": "zzz"}
  assert detect_bumps(old, new, ["opendbc"]) == ["opendbc"]


def test_ignores_paths_not_in_fork_list():
  old = {"panda": "aaa"}
  new = {"panda": "zzz"}
  assert detect_bumps(old, new, ["opendbc"]) == []


def test_missing_path_is_not_a_bump():
  assert detect_bumps({}, {"opendbc": "zzz"}, ["opendbc"]) == []


def test_default_fork_list_contains_opendbc():
  assert "opendbc" in FORK_SUBMODULES
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tools/ndm/test_submodules.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'openpilot.tools.ndm.submodules'`.

- [ ] **Step 3: Implement `submodules.py`**

Create `tools/ndm/submodules.py`:

```python
from __future__ import annotations

import subprocess

FORK_SUBMODULES = ["opendbc"]


def detect_bumps(old_shas: dict[str, str], new_shas: dict[str, str],
                 fork_paths: list[str]) -> list[str]:
  """Return fork submodule paths whose pinned SHA changed between two refs."""
  bumps = []
  for path in fork_paths:
    if path in old_shas and path in new_shas and old_shas[path] != new_shas[path]:
      bumps.append(path)
  return bumps


def read_submodule_shas(repo: str, ref: str, paths: list[str]) -> dict[str, str]:
  """Read the gitlink SHA each submodule path is pinned to at the given ref."""
  shas = {}
  for path in paths:
    result = subprocess.run(
      ["git", "rev-parse", f"{ref}:{path}"],
      cwd=repo, capture_output=True, text=True,
    )
    if result.returncode == 0:
      shas[path] = result.stdout.strip()
  return shas
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tools/ndm/test_submodules.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add tools/ndm/submodules.py tools/ndm/test_submodules.py
git commit -m "ndm: detect upstream bumps of fork submodules"
```

---

## Task 4: Git mechanics (integration-tested)

**Files:**
- Create: `tools/ndm/gitops.py`
- Test: `tools/ndm/test_gitops.py`

**Interfaces:**
- Produces:
  - `git(repo: str, *args: str) -> str` — run git in `repo`, return stripped stdout, raise `GitError` on failure.
  - `GitError(RuntimeError)`.
  - `add_upstream(repo: str, name: str, url: str) -> None` — idempotent `remote add` + `fetch`.
  - `fast_forward_master(repo: str, upstream_ref: str) -> bool` — FF local `master` to `upstream_ref`; return `True` if it moved, `False` if already current; raise `GitError` if not a fast-forward.
  - `create_trial_branch(repo: str, name: str, base: str) -> None` — create/reset `name` at `base`, checkout.
  - `rebase_tweaks(repo: str, base_ref: str, tip_ref: str, onto: str) -> str` — rebase `base_ref..tip_ref` onto `onto`; return `"clean"` on success or `"conflict"` if it stopped on a conflict (rebase left in progress for Claude).
  - `force_publish(repo: str, trial_branch: str, target_branch: str) -> None` — force-update `target_branch` to `trial_branch` and push `origin <target_branch>`.

- [ ] **Step 1: Write the failing integration tests**

Create `tools/ndm/test_gitops.py`:

```python
import subprocess

import pytest

from openpilot.tools.ndm import gitops


def _git(cwd, *args):
  return subprocess.run(["git", *args], cwd=cwd, check=True,
                        capture_output=True, text=True).stdout.strip()


def _commit(repo, name, content, msg):
  (repo / name).write_text(content)
  _git(repo, "add", ".")
  _git(repo, "commit", "-qm", msg)


@pytest.fixture
def repos(tmp_path):
  """upstream repo + a fork clone with one ndm commit on a 'ndm-dev' branch."""
  upstream = tmp_path / "upstream"
  upstream.mkdir()
  _git(upstream, "init", "-q", "-b", "master")
  _git(upstream, "config", "user.email", "t@t")
  _git(upstream, "config", "user.name", "t")
  _commit(upstream, "base.txt", "v1\n", "base")

  fork = tmp_path / "fork"
  _git(tmp_path, "clone", "-q", str(upstream), "fork")
  _git(fork, "config", "user.email", "t@t")
  _git(fork, "config", "user.name", "t")
  # fork's origin == upstream here; rename upstream remote for the test
  _git(fork, "remote", "rename", "origin", "upstream")
  _git(fork, "checkout", "-q", "-b", "ndm-dev")
  _commit(fork, "ndm.txt", "tweak\n", "ndm: my tweak")
  return {"upstream": upstream, "fork": fork}


def test_fast_forward_moves_master(repos):
  fork = str(repos["fork"])
  _commit(repos["upstream"], "base.txt", "v2\n", "upstream advance")
  gitops.add_upstream(fork, "upstream", str(repos["upstream"]))
  moved = gitops.fast_forward_master(fork, "upstream/master")
  assert moved is True
  assert (repos["fork"] / "base.txt").read_text() == "v2\n"


def test_fast_forward_noop_when_current(repos):
  fork = str(repos["fork"])
  gitops.add_upstream(fork, "upstream", str(repos["upstream"]))
  assert gitops.fast_forward_master(fork, "upstream/master") is False


def test_rebase_clean(repos):
  fork = str(repos["fork"])
  old_master = _git(repos["fork"], "rev-parse", "master")
  _commit(repos["upstream"], "base.txt", "v2\n", "upstream advance")
  gitops.add_upstream(fork, "upstream", str(repos["upstream"]))
  gitops.fast_forward_master(fork, "upstream/master")
  gitops.create_trial_branch(fork, "sync/test", "master")
  status = gitops.rebase_tweaks(fork, old_master, "ndm-dev", "sync/test")
  assert status == "clean"
  # the ndm tweak survived and sits on top of the new upstream content
  assert (repos["fork"] / "ndm.txt").read_text() == "tweak\n"
  assert (repos["fork"] / "base.txt").read_text() == "v2\n"


def test_rebase_conflict_left_in_progress(repos):
  fork = str(repos["fork"])
  # make the ndm commit and upstream both edit the SAME file → conflict
  _commit(repos["fork"], "shared.txt", "ndm-version\n", "ndm: edit shared")
  old_master = _git(repos["fork"], "rev-parse", "master")
  _commit(repos["upstream"], "shared.txt", "upstream-version\n", "upstream edit shared")
  gitops.add_upstream(fork, "upstream", str(repos["upstream"]))
  gitops.fast_forward_master(fork, "upstream/master")
  gitops.create_trial_branch(fork, "sync/test", "master")
  status = gitops.rebase_tweaks(fork, old_master, "ndm-dev", "sync/test")
  assert status == "conflict"
  # a rebase is genuinely in progress for Claude to finish
  assert (repos["fork"] / ".git" / "rebase-merge").exists() or \
         (repos["fork"] / ".git" / "rebase-apply").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tools/ndm/test_gitops.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'openpilot.tools.ndm.gitops'`.

- [ ] **Step 3: Implement `gitops.py`**

Create `tools/ndm/gitops.py`:

```python
from __future__ import annotations

import subprocess


class GitError(RuntimeError):
  pass


def git(repo: str, *args: str) -> str:
  result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
  if result.returncode != 0:
    raise GitError(f"git {' '.join(args)} failed:\n{result.stderr.strip()}")
  return result.stdout.strip()


def add_upstream(repo: str, name: str, url: str) -> None:
  existing = git(repo, "remote")
  if name not in existing.split():
    git(repo, "remote", "add", name, url)
  git(repo, "fetch", "--quiet", name)


def fast_forward_master(repo: str, upstream_ref: str) -> bool:
  git(repo, "checkout", "--quiet", "master")
  local = git(repo, "rev-parse", "master")
  remote = git(repo, "rev-parse", upstream_ref)
  if local == remote:
    return False
  # merge-base must equal local for a fast-forward; otherwise refuse
  base = git(repo, "merge-base", "master", upstream_ref)
  if base != local:
    raise GitError(f"master cannot fast-forward to {upstream_ref} "
                   f"(local {local[:9]} is not an ancestor)")
  git(repo, "merge", "--ff-only", upstream_ref)
  return True


def create_trial_branch(repo: str, name: str, base: str) -> None:
  git(repo, "checkout", "--quiet", "-B", name, base)


def rebase_tweaks(repo: str, base_ref: str, tip_ref: str, onto: str) -> str:
  """Rebase base_ref..tip_ref onto `onto`. Returns 'clean' or 'conflict'.

  On conflict the rebase is intentionally left in progress so Claude can
  finish it; on a clean rebase the trial branch (== `onto`) now carries the
  replayed tweaks.
  """
  result = subprocess.run(
    ["git", "rebase", "--onto", onto, base_ref, tip_ref],
    cwd=repo, capture_output=True, text=True,
  )
  if result.returncode == 0:
    return "clean"
  # distinguish a conflict (rebase paused) from a hard failure
  status = subprocess.run(["git", "status", "--porcelain=v1"], cwd=repo,
                          capture_output=True, text=True).stdout
  if "UU " in status or "AA " in status or "rebase" in git(repo, "status"):
    return "conflict"
  raise GitError(f"git rebase failed unexpectedly:\n{result.stderr.strip()}")


def force_publish(repo: str, trial_branch: str, target_branch: str) -> None:
  git(repo, "branch", "--force", target_branch, trial_branch)
  git(repo, "push", "--force", "origin", target_branch)
```

Note: `rebase_tweaks` rebases `base_ref..tip_ref` onto `onto`. After a clean rebase, git leaves HEAD detached at the replayed tip; the workflow records that SHA and the trial branch is updated by `sync.py` (Task 5) via `git checkout -B <trial> HEAD`. For the conflict path, HEAD stays mid-rebase for Claude.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tools/ndm/test_gitops.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add tools/ndm/gitops.py tools/ndm/test_gitops.py
git commit -m "ndm: git mechanics for ff-master + rebase + publish"
```

---

## Task 5: CLI orchestrator

**Files:**
- Create: `tools/ndm/sync.py`
- Test: `tools/ndm/test_sync.py`

**Interfaces:**
- Consumes: everything from `gitops`, `submodules`, `gate`, `report`.
- Produces: a CLI with three subcommands, run as `python -m openpilot.tools.ndm.sync <cmd>`:
  - `prepare --upstream-url URL --trial-branch NAME [--repo PATH] [--state PATH]` — adds upstream, FFs master, detects bumps, creates trial branch, rebases. Writes `sync-state.json` (`{old_master, new_master, rebase, bumps, trial_branch, noop}`) and prints those as `key=value` lines for `$GITHUB_OUTPUT`. Exits 0 even on `noop` (with `noop=true`).
  - `gate --ci-passed BOOL --report PATH [--state PATH]` — reads state + `sync-report.json`, prints `decision=publish|escalate`.
  - `publish --trial-branch NAME [--repo PATH]` — force-publishes the trial branch to `ndm-dev`.
- Module-level constant `TARGET_BRANCH = "ndm-dev"`, `NDM_TIP = "ndm-dev"` source ref for the tweak range.

- [ ] **Step 1: Write the failing test**

Create `tools/ndm/test_sync.py` (covers the pure state→decision plumbing and a `prepare` smoke run on a temp repo):

```python
import json
import subprocess

import pytest

from openpilot.tools.ndm import sync


def _git(cwd, *args):
  return subprocess.run(["git", *args], cwd=cwd, check=True,
                        capture_output=True, text=True).stdout.strip()


@pytest.fixture
def fork_with_upstream(tmp_path):
  upstream = tmp_path / "upstream"
  upstream.mkdir()
  _git(upstream, "init", "-q", "-b", "master")
  _git(upstream, "config", "user.email", "t@t")
  _git(upstream, "config", "user.name", "t")
  (upstream / "base.txt").write_text("v1\n")
  _git(upstream, "add", "."); _git(upstream, "commit", "-qm", "base")

  fork = tmp_path / "fork"
  _git(tmp_path, "clone", "-q", str(upstream), "fork")
  _git(fork, "config", "user.email", "t@t")
  _git(fork, "config", "user.name", "t")
  _git(fork, "checkout", "-q", "-b", "ndm-dev")
  (fork / "ndm.txt").write_text("tweak\n")
  _git(fork, "add", "."); _git(fork, "commit", "-qm", "ndm: tweak")
  # advance upstream so there is something to sync
  (upstream / "base.txt").write_text("v2\n")
  _git(upstream, "add", "."); _git(upstream, "commit", "-qm", "advance")
  return {"upstream": upstream, "fork": fork}


def test_decision_for_state_publishes_when_clean(tmp_path):
  state = {"rebase": "clean", "bumps": []}
  report = '{"status": "clean", "confidence": "high", "summary": "ok"}'
  assert sync.decision_for(state, ci_passed=True, report_text=report) == "publish"


def test_decision_for_state_escalates_on_bump(tmp_path):
  state = {"rebase": "clean", "bumps": ["opendbc"]}
  report = '{"status": "clean", "confidence": "high", "summary": "ok"}'
  assert sync.decision_for(state, ci_passed=True, report_text=report) == "escalate"


def test_decision_for_escalates_on_bad_report(tmp_path):
  state = {"rebase": "clean", "bumps": []}
  assert sync.decision_for(state, ci_passed=True, report_text="garbage") == "escalate"


def test_prepare_writes_state_and_rebases_clean(fork_with_upstream, tmp_path):
  fork = str(fork_with_upstream["fork"])
  state_path = tmp_path / "state.json"
  rc = sync.main([
    "prepare",
    "--upstream-url", str(fork_with_upstream["upstream"]),
    "--trial-branch", "sync/test",
    "--repo", fork,
    "--state", str(state_path),
  ])
  assert rc == 0
  state = json.loads(state_path.read_text())
  assert state["noop"] is False
  assert state["rebase"] == "clean"
  assert state["bumps"] == []
  # trial branch exists and carries the tweak on top of advanced upstream
  assert _git(fork, "rev-parse", "--verify", "sync/test")
  _git(fork, "checkout", "-q", "sync/test")
  assert (fork_with_upstream["fork"] / "base.txt").read_text() == "v2\n"
  assert (fork_with_upstream["fork"] / "ndm.txt").read_text() == "tweak\n"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tools/ndm/test_sync.py -v`
Expected: FAIL — `AttributeError`/`ModuleNotFoundError` (no `sync` module yet).

- [ ] **Step 3: Implement `sync.py`**

Create `tools/ndm/sync.py`:

```python
from __future__ import annotations

import argparse
import json
import os
import sys

from openpilot.tools.ndm import gitops, submodules
from openpilot.tools.ndm.gate import decide
from openpilot.tools.ndm.report import ReportError, parse_report

TARGET_BRANCH = "ndm-dev"
NDM_TIP = "ndm-dev"
UPSTREAM_REMOTE = "upstream"


def _emit_outputs(values: dict) -> None:
  """Write key=value lines to $GITHUB_OUTPUT if running in Actions."""
  path = os.environ.get("GITHUB_OUTPUT")
  if not path:
    return
  with open(path, "a") as f:
    for key, value in values.items():
      f.write(f"{key}={json.dumps(value) if isinstance(value, (list, dict)) else value}\n")


def decision_for(state: dict, *, ci_passed: bool, report_text: str) -> str:
  try:
    report = parse_report(report_text)
  except ReportError:
    return "escalate"
  if state.get("rebase") == "conflict" and report.status == "clean":
    # a conflict that Claude claims is 'clean' is contradictory → distrust it
    return "escalate"
  return decide(ci_passed=ci_passed, report=report, submodule_bumps=state.get("bumps", []))


def cmd_prepare(args) -> int:
  repo = args.repo
  gitops.add_upstream(repo, UPSTREAM_REMOTE, args.upstream_url)
  old_master = gitops.git(repo, "rev-parse", "master")
  upstream_ref = f"{UPSTREAM_REMOTE}/master"

  moved = gitops.fast_forward_master(repo, upstream_ref)
  new_master = gitops.git(repo, "rev-parse", "master")

  state = {
    "old_master": old_master,
    "new_master": new_master,
    "trial_branch": args.trial_branch,
    "noop": not moved,
    "rebase": None,
    "bumps": [],
  }

  if not moved:
    _write_state(args.state, state)
    _emit_outputs({"noop": "true"})
    print("nothing new upstream; no-op")
    return 0

  old_shas = submodules.read_submodule_shas(repo, old_master, submodules.FORK_SUBMODULES)
  new_shas = submodules.read_submodule_shas(repo, new_master, submodules.FORK_SUBMODULES)
  state["bumps"] = submodules.detect_bumps(old_shas, new_shas, submodules.FORK_SUBMODULES)

  gitops.create_trial_branch(repo, args.trial_branch, "master")
  rebase_status = gitops.rebase_tweaks(repo, old_master, NDM_TIP, args.trial_branch)
  state["rebase"] = rebase_status
  if rebase_status == "clean":
    # rebase left HEAD detached at the replayed tip; re-point the trial branch
    gitops.git(repo, "checkout", "-B", args.trial_branch, "HEAD")

  _write_state(args.state, state)
  _emit_outputs({
    "noop": "false",
    "rebase": rebase_status,
    "bumps": state["bumps"],
    "trial_branch": args.trial_branch,
  })
  print(f"prepared trial branch {args.trial_branch}: rebase={rebase_status}, bumps={state['bumps']}")
  return 0


def cmd_gate(args) -> int:
  state = json.loads(_read(args.state))
  report_text = _read(args.report) if os.path.exists(args.report) else ""
  decision = decision_for(state, ci_passed=args.ci_passed, report_text=report_text)
  _emit_outputs({"decision": decision})
  print(f"decision={decision}")
  return 0


def cmd_publish(args) -> int:
  gitops.force_publish(args.repo, args.trial_branch, TARGET_BRANCH)
  print(f"published {args.trial_branch} -> {TARGET_BRANCH}")
  return 0


def _write_state(path: str, state: dict) -> None:
  with open(path, "w") as f:
    json.dump(state, f, indent=2)


def _read(path: str) -> str:
  with open(path) as f:
    return f.read()


def _str2bool(v: str) -> bool:
  return str(v).strip().lower() in ("1", "true", "yes", "y")


def main(argv=None) -> int:
  parser = argparse.ArgumentParser(prog="ndm-sync")
  sub = parser.add_subparsers(dest="cmd", required=True)

  p = sub.add_parser("prepare")
  p.add_argument("--upstream-url", required=True)
  p.add_argument("--trial-branch", required=True)
  p.add_argument("--repo", default=".")
  p.add_argument("--state", default="sync-state.json")
  p.set_defaults(func=cmd_prepare)

  g = sub.add_parser("gate")
  g.add_argument("--ci-passed", type=_str2bool, required=True)
  g.add_argument("--report", default="sync-report.json")
  g.add_argument("--state", default="sync-state.json")
  g.set_defaults(func=cmd_gate)

  pub = sub.add_parser("publish")
  pub.add_argument("--trial-branch", required=True)
  pub.add_argument("--repo", default=".")
  pub.set_defaults(func=cmd_publish)

  args = parser.parse_args(argv)
  return args.func(args)


if __name__ == "__main__":
  sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tools/ndm/test_sync.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Run the whole package suite**

Run: `pytest tools/ndm/ -v`
Expected: PASS (all tasks' tests green).

- [ ] **Step 6: Commit**

```bash
git add tools/ndm/sync.py tools/ndm/test_sync.py
git commit -m "ndm: sync CLI (prepare/gate/publish)"
```

---

## Task 6: Claude prompt + contract test

**Files:**
- Create: `tools/ndm/sync-prompt.md`
- Test: `tools/ndm/test_prompt_contract.py`

**Interfaces:**
- Produces: a prompt file containing exactly one fenced ```json block that is a valid example `sync-report.json`. The test extracts that block and asserts it parses via `parse_report`, keeping the prompt and schema in lockstep.

- [ ] **Step 1: Write the failing test**

Create `tools/ndm/test_prompt_contract.py`:

```python
import os
import re

from openpilot.tools.ndm.report import parse_report

PROMPT = os.path.join(os.path.dirname(__file__), "sync-prompt.md")


def _example_json() -> str:
  text = open(PROMPT).read()
  match = re.search(r"```json\n(.*?)\n```", text, re.DOTALL)
  assert match, "sync-prompt.md must contain a ```json example block"
  return match.group(1)


def test_prompt_example_matches_schema():
  report = parse_report(_example_json())
  assert report.status in ("clean", "resolved", "risky")
  assert report.confidence in ("high", "low")


def test_prompt_mentions_no_drop_rule():
  text = open(PROMPT).read().lower()
  assert "ndm:" in text
  assert "sync-report.json" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tools/ndm/test_prompt_contract.py -v`
Expected: FAIL — `FileNotFoundError` for `sync-prompt.md`.

- [ ] **Step 3: Write `sync-prompt.md`**

Create `tools/ndm/sync-prompt.md`:

````markdown
# Upstream sync: conflict resolution + semantic review

You are running inside a GitHub Actions runner in a checkout of a personal
sunnypilot fork. `master` has just been fast-forwarded to the latest upstream
sunnypilot, and the owner's `ndm:` commits are being rebased onto it on the
trial branch. Your job has two parts.

## Part 1 — Finish the rebase (only if one is in progress)

If `git status` shows a rebase in progress, resolve every conflict and run
`git rebase --continue` until the rebase completes. Rules:

- Resolve each conflict honoring the **intent of the `ndm:` commit** being
  replayed (read its message and diff with `git log` / `git show`).
- **Never drop `ndm:` functionality** to make a conflict disappear. The owner
  wants every tweak preserved. If upstream restructured the code so a tweak no
  longer applies cleanly, re-implement the tweak's intent against the new code.
- If you cannot confidently preserve a tweak's intent, set `confidence` to
  `low` rather than guessing.

## Part 2 — Semantic review (always)

Even when the rebase was clean, check each `ndm:` commit for *silent* breakage:
for every file a tweak touches, compare what upstream changed (between the old
and new `master`) against what the tweak relies on. Flag any case where
upstream moved, renamed, or changed the behavior of an API/param/signature the
tweak depends on — even though git merged it without a textual conflict.

## Output — write two files at the repo root

1. `sync-report.json` — machine-read by the gate. Exact schema:

```json
{
  "status": "resolved",
  "confidence": "high",
  "summary": "Rebased 10 ndm commits; resolved 1 conflict in sidebar.py.",
  "flags": [
    {"type": "semantic", "file": "selfdrive/ui/layouts/sidebar.py", "detail": "upstream renamed draw_rectangle_rec; verify the teal marker still draws"}
  ]
}
```

- `status`: `clean` (no conflicts, no re-implementation), `resolved` (conflicts
  fixed with intent preserved), or `risky` (something you could not fully trust).
- `confidence`: `high` only if every tweak's intent is preserved and you found
  no unresolved semantic risk; otherwise `low`.
- `flags`: one entry per semantic risk. **Any flag, `low` confidence, or
  `risky` status will stop the auto-publish and open a review PR instead** — so
  do not invent flags, but never hide a real one.

2. `sync-report.md` — a human-readable writeup used as the PR body when the sync
   is escalated: what upstream changed, what you did per conflict, and each flag.
````

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tools/ndm/test_prompt_contract.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add tools/ndm/sync-prompt.md tools/ndm/test_prompt_contract.py
git commit -m "ndm: Claude sync prompt + schema lockstep test"
```

---

## Task 7: GitHub Actions workflow + runbook

**Files:**
- Create: `.github/workflows/ndm-sync.yaml`
- Create: `docs/ndm/upstream-sync.md`

**Interfaces:**
- Consumes: `python -m openpilot.tools.ndm.sync` subcommands; `tools/ndm/sync-prompt.md`; secret `CLAUDE_CODE_OAUTH_TOKEN`.
- Produces: a workflow with `schedule` (weekly) + `workflow_dispatch` (with a `publish` boolean input defaulting to `false` for dry-run trust-building).

- [ ] **Step 1: Install actionlint locally**

Run: `brew install actionlint`
Expected: actionlint installed (verify `actionlint --version`). If Homebrew is unavailable, download the binary from the actionlint releases page instead.

- [ ] **Step 2: Write the workflow**

Create `.github/workflows/ndm-sync.yaml`:

```yaml
name: ndm-sync

on:
  schedule:
    - cron: "0 9 * * 0"   # Sundays 09:00 UTC
  workflow_dispatch:
    inputs:
      publish:
        description: "Auto-publish to ndm-dev when green (false = always open a PR)"
        type: boolean
        default: false

concurrency:
  group: ndm-sync
  cancel-in-progress: false

permissions:
  contents: write
  pull-requests: write
  actions: write   # to dispatch tests.yaml

jobs:
  sync:
    runs-on: ubuntu-latest
    env:
      UPSTREAM_URL: https://github.com/sunnypilot/sunnypilot.git
      PYTHONPATH: ${{ github.workspace }}
      GH_TOKEN: ${{ github.token }}
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0
          ref: ndm-dev

      - name: Configure git identity
        run: |
          git config user.name "ndm-sync-bot"
          git config user.email "ndm-sync@users.noreply.github.com"

      - name: Compute trial branch name
        id: name
        run: echo "trial=sync/$(date +%F)" >> "$GITHUB_OUTPUT"

      - name: Prepare (ff master, detect bumps, rebase)
        id: prep
        run: |
          python -m openpilot.tools.ndm.sync prepare \
            --upstream-url "$UPSTREAM_URL" \
            --trial-branch "${{ steps.name.outputs.trial }}" \
            --state sync-state.json

      - name: Stop if nothing new
        if: steps.prep.outputs.noop == 'true'
        run: echo "Nothing new upstream. Done." && exit 0

      - name: Resolve conflicts + semantic review (Claude)
        if: steps.prep.outputs.noop != 'true'
        uses: anthropics/claude-code-action@v1
        with:
          claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
          prompt_file: tools/ndm/sync-prompt.md

      - name: Push trial branch
        if: steps.prep.outputs.noop != 'true'
        run: git push --force origin "${{ steps.name.outputs.trial }}"

      - name: Run device build + tests against trial branch
        id: ci
        if: steps.prep.outputs.noop != 'true'
        run: |
          gh workflow run tests.yaml --ref "${{ steps.name.outputs.trial }}"
          # poll the run we just kicked off on this ref
          for i in $(seq 1 60); do
            sleep 30
            run_json=$(gh run list --workflow tests.yaml \
              --branch "${{ steps.name.outputs.trial }}" --limit 1 \
              --json status,conclusion,databaseId)
            status=$(echo "$run_json" | python -c "import sys,json;print(json.load(sys.stdin)[0]['status'])")
            if [ "$status" = "completed" ]; then
              concl=$(echo "$run_json" | python -c "import sys,json;print(json.load(sys.stdin)[0]['conclusion'])")
              echo "ci_passed=$([ "$concl" = "success" ] && echo true || echo false)" >> "$GITHUB_OUTPUT"
              exit 0
            fi
          done
          echo "ci_passed=false" >> "$GITHUB_OUTPUT"

      - name: Gate decision
        id: gate
        if: steps.prep.outputs.noop != 'true'
        run: |
          python -m openpilot.tools.ndm.sync gate \
            --ci-passed "${{ steps.ci.outputs.ci_passed }}" \
            --report sync-report.json \
            --state sync-state.json

      - name: Publish (force-push ndm-dev)
        if: >
          steps.prep.outputs.noop != 'true' &&
          steps.gate.outputs.decision == 'publish' &&
          (github.event_name == 'schedule' || inputs.publish)
        run: |
          python -m openpilot.tools.ndm.sync publish \
            --trial-branch "${{ steps.name.outputs.trial }}"

      - name: Escalate (open review PR)
        if: >
          steps.prep.outputs.noop != 'true' &&
          (steps.gate.outputs.decision == 'escalate' ||
           (github.event_name == 'workflow_dispatch' && !inputs.publish))
        run: |
          body_file=sync-report.md
          [ -f "$body_file" ] || echo "Automated sync needs review." > "$body_file"
          gh pr create \
            --base ndm-dev \
            --head "${{ steps.name.outputs.trial }}" \
            --title "ndm-sync: review ${{ steps.name.outputs.trial }}" \
            --body-file "$body_file" \
            --assignee nparcher24
```

- [ ] **Step 3: Lint the workflow**

Run: `actionlint .github/workflows/ndm-sync.yaml`
Expected: no output (exit 0). Fix any reported issues until clean.

- [ ] **Step 4: Write the runbook**

Create `docs/ndm/upstream-sync.md`:

```markdown
# Autonomous upstream sync

Keeps `ndm-dev` = latest sunnypilot upstream + the `ndm:` tweaks, automatically.

## One-time setup
1. Generate a Claude Code OAuth token on your machine: `claude setup-token`.
2. Add it as repo secret `CLAUDE_CODE_OAUTH_TOKEN`
   (GitHub → Settings → Secrets and variables → Actions).
3. Confirm Actions can create PRs: Settings → Actions → General →
   "Allow GitHub Actions to create and approve pull requests".

## How it runs
- Weekly (Sun 09:00 UTC) and on demand (Actions → ndm-sync → Run workflow).
- It fast-forwards `master`, rebases the `ndm:` commits onto a `sync/<date>`
  branch, has Claude resolve conflicts + review, runs `tests.yaml`
  (incl. `build.py`, the device's on-boot build) against that branch, then:
  - **all green & low risk →** force-pushes `ndm-dev`. Your car picks it up on
    its next Settings → Software → check-for-update.
  - **anything risky →** opens a PR assigned to you; `ndm-dev` is untouched.

## Building trust (dry-run)
Manual runs default to `publish=false`: they always open a PR instead of
pushing, so you can watch several real syncs first. Once confident, the weekly
scheduled run auto-publishes. To force a manual run to auto-publish, set the
`publish` input to true.

## When a PR shows up
Review Claude's writeup (PR body) and the diff. If good, merge; the next sync
(or a manual publish run) advances `ndm-dev`. If a flag points at a real break,
fix it on the `sync/<date>` branch and merge.

## Submodule bumps (opendbc)
If upstream bumps the `opendbc` pointer, the run escalates (your opendbc is a
fork). Rebase your opendbc fork onto the new SHA, push it, update the gitlink,
then re-run. (Automating this is a future enhancement.)
```

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ndm-sync.yaml docs/ndm/upstream-sync.md
git commit -m "ndm: scheduled upstream-sync workflow + runbook"
```

---

## Self-Review Notes

- **Spec coverage:** rebase strategy (Task 4/5, Global Constraints) ✔; FF-only master (gitops + escalate) ✔; submodule-bump detect-and-notify (Task 3, gate) ✔; semantic review (Task 6 prompt + flags → gate) ✔; build gate via `tests.yaml`/`build.py` (Task 7) ✔; publish-only-when-green gate (Task 2/5) ✔; escalate-via-PR (Task 7) ✔; OAuth auth (Task 7 + runbook) ✔; dry-run mode (Task 7 `publish` input + runbook) ✔; `ndm-dev` mutated only at publish (workflow ordering) ✔; force-push safe (documented) ✔.
- **Deferred (matches spec non-goals):** opendbc fork auto-rebase (escalates instead); richer notifications (GitHub-native only).
- **Type consistency:** `decide(ci_passed, report, submodule_bumps)`, `parse_report`, `SyncReport`/`Flag`, `detect_bumps`, `rebase_tweaks` return values (`"clean"`/`"conflict"`), and `decision_for` are referenced consistently across Tasks 1–7.
- **Verification nuance (flag for executor):** Task 7's `gh run list --branch` poll assumes the most recent `tests.yaml` run on the trial branch is the one we dispatched. Since the branch is freshly created per sync this is safe in practice, but if flakiness appears, switch to capturing the dispatched run id via the API. Note this when implementing.
- **External-action input names (verify before relying on Task 7):** `anthropics/claude-code-action`'s exact input keys (`claude_code_oauth_token`, `prompt_file` vs `prompt`) and current major version tag must be confirmed against its README at implementation time — pin the version and adjust the `with:` keys to match. The orchestration logic does not depend on the exact names, only the resolve+review+write-`sync-report.*` behavior.
