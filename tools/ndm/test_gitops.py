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
