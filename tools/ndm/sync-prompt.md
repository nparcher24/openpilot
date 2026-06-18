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
