# Autonomous Upstream Sync — Design

**Date:** 2026-06-18
**Status:** Approved design, pre-implementation
**Repo:** `nparcher24/openpilot` (local: `sunnypilot-ndm`), branch model: `master` tracks upstream sunnypilot, `ndm-dev` = `master` + personal `ndm:` commits, the device flashes `ndm-dev`.

## Goal

Keep `ndm-dev` continuously equal to **(latest sunnypilot upstream) + (my `ndm:` tweaks)** with no manual effort on the happy path. New upstream code should reach the car automatically — *but only when it has been verified to still build the way the device builds it*, and never at the cost of silently dropping or breaking my tweaks. When a sync is genuinely risky, the automation must stop short of publishing and pull me in instead.

## Non-goals (v1)

- Auto-rebasing the `opendbc` **fork** (`nparcher24/opendbc`) when upstream bumps the submodule pointer. v1 **detects and notifies**; the fork is handled manually. (Candidate for v2.)
- Producing a `prebuilt` device image. The device builds on boot; we only need the *source* to be correct and buildable.
- Replacing the device's existing update path. The on-device updater (`system/updated/updated.py`) already hard-resets to `origin/ndm-dev` (`git fetch` + `git checkout --force -B ndm-dev FETCH_HEAD` + `reset --hard`), which is **force-push-safe**. We rely on that unchanged.

## Key facts this design rests on

- `ndm-dev` is a small, clean stack of `ndm:`-prefixed commits on top of `master` (10 at design time, 0 behind).
- The device updater hard-resets to the remote branch, so **rebasing `ndm-dev` and force-pushing is safe** for the car.
- Upstream CI (`.github/workflows/tests.yaml`) already contains the gold-standard gate: a `build_release` job that runs **`python3 system/manager/build.py`** — the *exact* build the 3X runs on first boot — plus `unit_tests` (scons + pytest) and `static_analysis`. `tests.yaml` exposes `workflow_dispatch`, so it can be run on demand against an arbitrary ref.
- Only `opendbc` among the submodules is *my* fork; the rest point at sunnypilot/comma.

## Integration strategy

**Rebase**, not merge. `ndm-dev` has no collaborators (only the device consumes it), so force-push is free, and a rebase produces a clean linear stack of exactly my `ndm:` commits on each new upstream base. Per-commit conflicts are also far easier for an LLM to reason about in isolation than one giant merge blob.

## Execution model

A **scheduled GitHub Action** (cloud), so it runs independently of whether the Mac is on. Trigger: weekly `schedule` (cron) + `workflow_dispatch` for manual runs. All work happens on disposable runner checkouts and trial branches; `ndm-dev` is only ever touched at the final publish step.

## Architecture / flow

The orchestrator workflow (`.github/workflows/ndm-sync.yaml`) runs these stages in order. Any stage that fails or raises a blocking flag routes to **Escalate** instead of **Publish**.

### 1. Prepare
- Checkout the fork with full history and a token that can push.
- Add `upstream = https://github.com/sunnypilot/sunnypilot.git`, `git fetch upstream`.
- Record `OLD_MASTER = origin/master`.
- Fast-forward `master` to `upstream/master`.
  - If `master` cannot fast-forward (unexpected local divergence on master) → **Escalate** (do not rewrite master).
- If `upstream/master == OLD_MASTER` (nothing new) → exit cleanly, no-op, no notification.

### 2. Detect submodule-pointer changes (notify-only in v1)
- Diff the `opendbc` gitlink between `OLD_MASTER` and the new `master`.
- If upstream moved `opendbc` (or any submodule that is my fork), record a **blocking flag** `submodule-bump` with details. (My fork would need its own rebase before the device can clone the new SHA, which v1 does not automate.)

### 3. Rebase the tweaks
- Create trial branch `sync/<YYYY-MM-DD>` at the new `master`.
- Rebase the range `OLD_MASTER..ndm-dev` onto it.
- **Clean rebase** → status `clean`.
- **Conflicts** → invoke Claude (see §Conflict resolution) to resolve them; status `resolved` with a confidence verdict.

### 4. Semantic review (runs even on a clean rebase)
This is how "don't mess with my changes" is enforced beyond textual conflicts. For each `ndm:` commit, Claude diffs the files it touches against what upstream changed between `OLD_MASTER` and new `master`, and flags cases where upstream moved/renamed an API, signature, param, or behavior the patch depends on — *even when git merged cleanly*. Each such case is a **blocking flag**.

### 5. Verify (the build gate)
- `git push origin sync/<date>` (trial branch only).
- `gh workflow run tests.yaml --ref sync/<date>` (or API equivalent), then poll the run to completion.
- Require success of at least: `build_release` (= `build.py`), `unit_tests`, `static_analysis`.
- Any failure → **Escalate** (attach failing job logs/links).

### 6. Gate → Publish or Escalate
**Publish** (force-push `sync/<date>` → `ndm-dev`) **iff all** hold:
- CI required jobs are green, **and**
- rebase status ∈ {`clean`, `resolved`}, **and**
- Claude confidence is `high`, **and**
- there are no blocking flags (semantic risk, submodule bump, etc.).

On publish: force-push to `ndm-dev`, delete the trial branch, write a short success note (the car picks it up on its next update check — **zero input from me**).

Otherwise **Escalate**: leave `ndm-dev` untouched, open a PR `sync/<date>` → `ndm-dev` containing Claude's writeup (what upstream changed, what it did, every flag and why it's unsure), assign it to me so GitHub emails me. Nothing reaches the car until I review, fix if needed, and merge — at which point publish happens.

## Conflict resolution (Claude in CI)

- **Auth:** `CLAUDE_CODE_OAUTH_TOKEN` GitHub secret (from `claude setup-token`, uses my Claude Max subscription — no API billing). Refreshed periodically when it expires.
- **Mechanism:** `anthropics/claude-code-action` (headless) operating on the runner's checkout mid-rebase.
- **Prompt contract:** resolve each conflict honoring the *intent* of the `ndm:` commit being replayed; never drop `ndm:` functionality to make a conflict go away; if intent can't be preserved confidently, mark low confidence rather than guessing.
- **Structured output contract:** Claude writes two artifacts the workflow consumes:
  - `sync-report.json` — `{ status: "clean"|"resolved"|"risky", confidence: "high"|"low", flags: [ {type, file, detail} ], summary: string }`
  - `sync-report.md` — human-readable writeup used as the PR body on Escalate.
- The gate (§6) reads `sync-report.json`. `status: "risky"`, `confidence: "low"`, or any blocking flag forces Escalate.

## Components / files

| File | Purpose |
|------|---------|
| `.github/workflows/ndm-sync.yaml` | Orchestrator: schedule/dispatch, prepare, gate, publish/escalate. |
| `tools/ndm/sync.sh` (or `.py`) | The git mechanics (add upstream, FF master, rebase, detect submodule bumps, push, force-publish), callable both in CI and locally for debugging. Keeps logic out of YAML. |
| Claude prompt file (e.g. `tools/ndm/sync-prompt.md`) | The resolution + semantic-review instructions and the JSON/MD output contract. |
| Repo secrets | `CLAUDE_CODE_OAUTH_TOKEN`; push uses `GITHUB_TOKEN` unless branch protection requires a PAT. |

Keeping the git mechanics in a standalone script (not inline YAML) means the same logic can be run by hand on the Mac (Approach B/C fallback) without rewriting it.

## Error handling

- **Master won't fast-forward** → Escalate, never rewrite `master`.
- **CI fails** → Escalate with logs.
- **Rebase low-confidence / semantic flag / submodule bump** → Escalate.
- **Claude/action error or token expired** → Escalate with the error (fail safe: never publish on uncertainty).
- **Nothing new upstream** → silent no-op.
- The car is *never* at risk from a failed run: `ndm-dev` is only mutated at the final publish step, which is reached only when every gate is green.

## Testing strategy

- **Dry-run mode** (`workflow_dispatch` input `publish: false`): run the whole pipeline but stop before force-pushing `ndm-dev` — always open the PR instead. Use this for the first several real syncs to build trust before letting it auto-publish.
- **Synthetic-conflict test:** craft a throwaway upstream-like change that collides with a known `ndm:` commit (e.g. the steering-cap commit) on a scratch branch, and confirm the workflow resolves, reports, and gates correctly without touching `ndm-dev`.
- **No-op test:** run when `master` is already current; confirm clean exit, no PR, no notification.
- Validate `sync-report.json` against its schema in the gate step so a malformed verdict Escalates rather than mis-publishes.

## Notifications

GitHub-native: the Escalate PR is assigned to me, which emails me. No extra infra in v1. (A richer push/Discord ping is a later add-on and doesn't change the core.)

## Open questions / deferred

- **Schedule cadence** — default weekly; tune after observing how often upstream moves and how often syncs Escalate.
- **opendbc fork auto-rebase** — v2.
- **PAT vs `GITHUB_TOKEN`** — start with `GITHUB_TOKEN`; switch to a fine-grained PAT only if branch protection on `ndm-dev`/`master` rejects the push.
