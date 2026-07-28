from __future__ import annotations

import subprocess

# Submodule *paths* (gitlink entries), not names. The opendbc submodule is
# named "opendbc" but lives at path "opendbc_repo"; a symlink blob named
# "opendbc" shadows it, so `git rev-parse <ref>:opendbc` silently returns a blob
# SHA that never moves — using the name here quietly disabled bump detection.
FORK_SUBMODULES = ["opendbc_repo"]


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
