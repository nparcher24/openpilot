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
