import subprocess

from tools.ndm.submodules import FORK_SUBMODULES, read_submodule_shas, detect_bumps  # noqa: TID251


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


def test_default_fork_list_uses_the_gitlink_path():
  # The submodule is *named* opendbc but its path (gitlink) is opendbc_repo.
  # FORK_SUBMODULES must hold the path, since read_submodule_shas resolves
  # `<ref>:<entry>` and only the path yields the 160000 gitlink SHA.
  assert "opendbc_repo" in FORK_SUBMODULES
  assert "opendbc" not in FORK_SUBMODULES


def _run(repo, *args):
  subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def test_read_submodule_shas_reads_the_gitlink_not_a_shadowing_blob(tmp_path):
  # Regression: our tree has a symlink blob at `opendbc` shadowing the real
  # gitlink at `opendbc_repo`. Reading the wrong entry returns a blob SHA that
  # never changes across upstream bumps, silently disabling the escalation.
  repo = tmp_path
  _run(repo, "init", "-q")
  _run(repo, "config", "user.email", "t@t")
  _run(repo, "config", "user.name", "t")
  # a blob at `opendbc` (mimics the shadowing symlink) ...
  (repo / "opendbc").write_text("../opendbc_repo")
  _run(repo, "add", "opendbc")
  # ... and a real gitlink at `opendbc_repo`.
  gitlink = "1111111111111111111111111111111111111111"
  _run(repo, "update-index", "--add", "--cacheinfo", f"160000,{gitlink},opendbc_repo")
  _run(repo, "commit", "-qm", "fixture")

  shas = read_submodule_shas(str(repo), "HEAD", ["opendbc_repo"])
  assert shas == {"opendbc_repo": gitlink}

  # Reading the shadowing blob entry must NOT be mistaken for the gitlink.
  blob = read_submodule_shas(str(repo), "HEAD", ["opendbc"])
  assert blob.get("opendbc") != gitlink
