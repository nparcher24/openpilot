import json
import subprocess

import pytest

from tools.ndm import sync  # noqa: TID251


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
  _git(upstream, "add", ".")
  _git(upstream, "commit", "-qm", "base")

  fork = tmp_path / "fork"
  _git(tmp_path, "clone", "-q", str(upstream), "fork")
  _git(fork, "config", "user.email", "t@t")
  _git(fork, "config", "user.name", "t")
  _git(fork, "checkout", "-q", "-b", "ndm-dev")
  (fork / "ndm.txt").write_text("tweak\n")
  _git(fork, "add", ".")
  _git(fork, "commit", "-qm", "ndm: tweak")
  # advance upstream so there is something to sync
  (upstream / "base.txt").write_text("v2\n")
  _git(upstream, "add", ".")
  _git(upstream, "commit", "-qm", "advance")
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


def test_decision_for_escalates_on_conflict_claims_clean():
  state = {"rebase": "conflict", "bumps": []}
  report = '{"status": "clean", "confidence": "high", "summary": "ok"}'
  assert sync.decision_for(state, ci_passed=True, report_text=report) == "escalate"


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


def test_prepare_syncs_when_master_already_at_upstream_tip(fork_with_upstream, tmp_path):
  """Regression: noop must mean 'ndm-dev already contains upstream', NOT 'master
  did not move this run'. A prior run's Mirror step can advance master to the
  upstream tip while ndm-dev is still behind; the sync must still rebase, else it
  goes no-op forever and the backlog never lands."""
  fork = str(fork_with_upstream["fork"])
  upstream = str(fork_with_upstream["upstream"])
  # Simulate the prior Mirror step: local master == upstream tip, ndm-dev behind.
  _git(fork, "fetch", "-q", upstream, "master")
  _git(fork, "checkout", "-q", "master")
  _git(fork, "reset", "-q", "--hard", "FETCH_HEAD")
  _git(fork, "checkout", "-q", "ndm-dev")

  state_path = tmp_path / "state.json"
  rc = sync.main([
    "prepare",
    "--upstream-url", upstream,
    "--trial-branch", "sync/test",
    "--repo", fork,
    "--state", str(state_path),
  ])
  assert rc == 0
  state = json.loads(state_path.read_text())
  assert state["noop"] is False          # was True under the old master-moved logic
  assert state["rebase"] == "clean"
  _git(fork, "checkout", "-q", "sync/test")
  assert (fork_with_upstream["fork"] / "base.txt").read_text() == "v2\n"
  assert (fork_with_upstream["fork"] / "ndm.txt").read_text() == "tweak\n"


def test_prepare_is_noop_when_ndm_dev_already_contains_upstream(fork_with_upstream, tmp_path):
  """The genuine no-op: ndm-dev already sits on top of the upstream tip."""
  fork = str(fork_with_upstream["fork"])
  upstream = str(fork_with_upstream["upstream"])
  # Rebase ndm-dev onto the advanced upstream so it already contains the tip.
  _git(fork, "fetch", "-q", upstream, "master")
  _git(fork, "rebase", "-q", "FETCH_HEAD", "ndm-dev")

  state_path = tmp_path / "state.json"
  rc = sync.main([
    "prepare",
    "--upstream-url", upstream,
    "--trial-branch", "sync/test",
    "--repo", fork,
    "--state", str(state_path),
  ])
  assert rc == 0
  state = json.loads(state_path.read_text())
  assert state["noop"] is True


def test_publish_guard_rejects_empty_trial(fork_with_upstream, tmp_path):
  """cmd_publish returns non-zero when trial branch has no commits ahead of master."""
  fork = str(fork_with_upstream["fork"])
  # The fixture already has origin; point it at a bare throwaway so any
  # accidental push attempt hits a safe target
  bare = tmp_path / "bare"
  bare.mkdir()
  _git(bare, "init", "-q", "--bare", "-b", "master")
  _git(fork, "remote", "set-url", "origin", str(bare))

  # Create a trial branch that equals master (no tweaks ahead)
  _git(fork, "checkout", "-q", "master")
  _git(fork, "checkout", "-q", "-B", "sync/empty", "master")

  # cmd_publish should refuse with non-zero exit code before pushing
  import argparse
  args = argparse.Namespace(repo=fork, trial_branch="sync/empty")
  rc = sync.cmd_publish(args)
  assert rc != 0
