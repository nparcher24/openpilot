import subprocess

import pytest

from tools.ndm import gitops  # noqa: TID251


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


def test_fast_forward_raises_on_divergence(repos):
  """master diverged from upstream (local commit not on upstream) → GitError."""
  fork = str(repos["fork"])
  # Add a local commit to master that is NOT on upstream
  _git(fork, "checkout", "-q", "master")
  _commit(repos["fork"], "local-only.txt", "diverge\n", "local diverging commit")
  # Also advance upstream so they have genuinely diverged
  _commit(repos["upstream"], "base.txt", "v2\n", "upstream advance")
  gitops.add_upstream(fork, "upstream", str(repos["upstream"]))
  with pytest.raises(gitops.GitError):
    gitops.fast_forward_master(fork, "upstream/master")


def test_rebase_clean(repos):
  """trial branch created at ndm-dev tip, then rebased in-place onto master."""
  fork = str(repos["fork"])
  old_master = _git(repos["fork"], "rev-parse", "master")
  _commit(repos["upstream"], "base.txt", "v2\n", "upstream advance")
  gitops.add_upstream(fork, "upstream", str(repos["upstream"]))
  gitops.fast_forward_master(fork, "upstream/master")
  # New convention: trial starts at ndm-dev, rebase it onto master
  gitops.create_trial_branch(fork, "sync/test", "ndm-dev")
  status = gitops.rebase_tweaks(fork, old_master, "sync/test", "master")
  assert status == "clean"
  # Verify the branch ref (not just worktree) carries the tweak on top of new upstream
  _git(fork, "checkout", "sync/test")
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
  # New convention: trial starts at ndm-dev, rebase onto master
  gitops.create_trial_branch(fork, "sync/test", "ndm-dev")
  status = gitops.rebase_tweaks(fork, old_master, "sync/test", "master")
  assert status == "conflict"
  # a rebase is genuinely in progress for Claude to finish
  assert (repos["fork"] / ".git" / "rebase-merge").exists() or \
         (repos["fork"] / ".git" / "rebase-apply").exists()


def test_rebase_conflict_resolved_keeps_tweaks(repos):
  """After conflict → resolve → rebase --continue, trial branch has tweaks and ndm-dev is unchanged."""
  fork = str(repos["fork"])
  # Make the ndm commit and upstream both edit the SAME file → conflict
  _commit(repos["fork"], "shared.txt", "ndm-version\n", "ndm: edit shared")
  old_master = _git(repos["fork"], "rev-parse", "master")
  ndm_dev_sha_before = _git(repos["fork"], "rev-parse", "ndm-dev")
  _commit(repos["upstream"], "shared.txt", "upstream-version\n", "upstream edit shared")
  gitops.add_upstream(fork, "upstream", str(repos["upstream"]))
  gitops.fast_forward_master(fork, "upstream/master")

  gitops.create_trial_branch(fork, "sync/test", "ndm-dev")
  status = gitops.rebase_tweaks(fork, old_master, "sync/test", "master")
  assert status == "conflict"

  # Simulate Claude: write a resolved version and continue the rebase
  (repos["fork"] / "shared.txt").write_text("resolved-version\n")
  _git(fork, "add", "shared.txt")
  subprocess.run(
    ["git", "rebase", "--continue"],
    cwd=fork, check=True, capture_output=True, text=True,
    env={**__import__("os").environ, "GIT_EDITOR": "true"},
  )

  # sync/test should carry: upstream file == new content, ndm file == tweak, resolved file == resolved
  _git(fork, "checkout", "sync/test")
  assert (repos["fork"] / "base.txt").read_text() == "v1\n"
  assert (repos["fork"] / "ndm.txt").read_text() == "tweak\n"
  assert (repos["fork"] / "shared.txt").read_text() == "resolved-version\n"

  # The ndm-commit subject must appear in sync/test log
  log = _git(fork, "log", "--format=%s", "sync/test")
  assert "ndm: edit shared" in log

  # ndm-dev ref is UNCHANGED from before the rebase
  ndm_dev_sha_after = _git(repos["fork"], "rev-parse", "ndm-dev")
  assert ndm_dev_sha_before == ndm_dev_sha_after


def test_force_publish_moves_remote_branch(repos, tmp_path):
  """force_publish updates the remote branch ref to match the trial tip."""
  fork = str(repos["fork"])
  upstream = repos["upstream"]

  # Add origin (separate bare repo to act as the push target)
  bare = tmp_path / "bare"
  bare.mkdir()
  _git(bare, "init", "-q", "--bare", "-b", "master")
  _git(fork, "remote", "add", "origin", str(bare))
  # push ndm-dev as ndm-dev to origin so it exists there
  _git(fork, "push", "origin", "ndm-dev:ndm-dev")
  # Advance upstream so there's a new master to rebase onto
  _commit(upstream, "base.txt", "v2\n", "upstream advance")
  gitops.add_upstream(fork, "upstream", str(upstream))
  gitops.fast_forward_master(fork, "upstream/master")

  old_master = _git(repos["fork"], "rev-parse", "master~1")
  # Create trial branch at ndm-dev tip, rebase onto master
  gitops.create_trial_branch(fork, "sync/test", "ndm-dev")
  status = gitops.rebase_tweaks(fork, old_master, "sync/test", "master")
  assert status == "clean"

  trial_sha = _git(repos["fork"], "rev-parse", "sync/test")
  gitops.force_publish(fork, "sync/test", "ndm-dev")

  # The remote ndm-dev ref should now equal the trial tip
  remote_sha = _git(bare, "rev-parse", "ndm-dev")
  assert remote_sha == trial_sha
