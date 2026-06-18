from __future__ import annotations

import os
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

  On conflict the rebase is intentionally left in progress so the caller can
  finish it; on a clean rebase `tip_ref` (if it is a branch) ends up carrying
  the replayed tweaks on top of `onto`.
  """
  result = subprocess.run(
    ["git", "rebase", "--onto", onto, base_ref, tip_ref],
    cwd=repo, capture_output=True, text=True,
  )
  if result.returncode == 0:
    return "clean"
  # Distinguish a conflict (rebase paused) from a hard failure using the
  # structural rebase-state directories rather than free-text git status.
  for state_dir in ("rebase-merge", "rebase-apply"):
    git_path = subprocess.run(
      ["git", "rev-parse", "--git-path", state_dir],
      cwd=repo, capture_output=True, text=True,
    ).stdout.strip()
    if git_path:
      full_path = git_path if os.path.isabs(git_path) else os.path.join(repo, git_path)
      if os.path.exists(full_path):
        return "conflict"
  raise GitError(f"git rebase failed unexpectedly:\n{result.stderr.strip()}")


def force_publish(repo: str, trial_branch: str, target_branch: str) -> None:
  git(repo, "branch", "--force", target_branch, trial_branch)
  git(repo, "push", "--force", "origin", target_branch)
