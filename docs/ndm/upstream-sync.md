# Autonomous upstream sync

Keeps `ndm-dev` = latest sunnypilot upstream + the `ndm:` tweaks, automatically.

## One-time setup
1. Generate a Claude Code OAuth token on your machine: `claude setup-token`.
2. Add it as repo secret `CLAUDE_CODE_OAUTH_TOKEN`
   (GitHub → Settings → Secrets and variables → Actions).
3. Create a **`NDM_SYNC_PAT`** secret — a classic PAT (or fine-grained token)
   with the **`workflow`** scope on this repo. **Required:** upstream syncs
   routinely edit `.github/workflows/*`, and the built-in `GITHUB_TOKEN` is
   refused when a push touches workflow files (`refusing to allow a GitHub App
   to create or update workflow …`). Without this secret the run falls back to
   `GITHUB_TOKEN` and every such sync fails at the push step.
4. Confirm Actions can create PRs: Settings → Actions → General →
   "Allow GitHub Actions to create and approve pull requests".

### LFS note
The runner pushes with `--no-verify` and `GIT_LFS_SKIP_SMUDGE=1`: the LFS
binaries (fonts, `.onnx` models) already live on sunnypilot's GitLab and the
device fetches them there, so the runner never uploads LFS objects (it has no
SSH key for GitLab). Only the LFS *pointers* travel to GitHub, as normal git
blobs.

## How it runs
- Weekly (Sun 09:00 UTC) and on demand (Actions → ndm-sync → Run workflow).
- It fast-forwards `master`, rebases the `ndm:` commits onto a `sync/<date>`
  branch, has Claude resolve conflicts + review, runs `tests.yaml`
  (incl. `build.py`, the device's on-boot build) against that branch, then:
  - **all green & low risk →** force-pushes `ndm-dev`. Your car picks it up on
    its next Settings → Software → check-for-update.
  - **anything risky →** opens a PR assigned to you; `ndm-dev` is untouched.
  - **hard failure (push rejected, CI error, timeout) →** opens/updates a
    deduplicated `ndm-sync-failure` issue assigned to you, so a broken sync
    can't sit unnoticed. Close it once the sync is green again.

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
