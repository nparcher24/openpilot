from __future__ import annotations

import argparse
import json
import os
import sys

from openpilot.tools.ndm import gitops, submodules
from openpilot.tools.ndm.gate import decide
from openpilot.tools.ndm.report import ReportError, parse_report

TARGET_BRANCH = "ndm-dev"
NDM_TIP = "ndm-dev"
UPSTREAM_REMOTE = "upstream"


def _emit_outputs(values: dict) -> None:
  """Write key=value lines to $GITHUB_OUTPUT if running in Actions."""
  path = os.environ.get("GITHUB_OUTPUT")
  if not path:
    return
  with open(path, "a") as f:
    for key, value in values.items():
      f.write(f"{key}={json.dumps(value) if isinstance(value, (list, dict)) else value}\n")


def decision_for(state: dict, *, ci_passed: bool, report_text: str) -> str:
  try:
    report = parse_report(report_text)
  except ReportError:
    return "escalate"
  if state.get("rebase") == "conflict" and report.status == "clean":
    # a conflict that Claude claims is 'clean' is contradictory → distrust it
    return "escalate"
  return decide(ci_passed=ci_passed, report=report, submodule_bumps=state.get("bumps", []))


def cmd_prepare(args) -> int:
  repo = args.repo
  gitops.add_upstream(repo, UPSTREAM_REMOTE, args.upstream_url)
  old_master = gitops.git(repo, "rev-parse", "master")
  upstream_ref = f"{UPSTREAM_REMOTE}/master"

  moved = gitops.fast_forward_master(repo, upstream_ref)
  new_master = gitops.git(repo, "rev-parse", "master")

  state = {
    "old_master": old_master,
    "new_master": new_master,
    "trial_branch": args.trial_branch,
    "noop": not moved,
    "rebase": None,
    "bumps": [],
  }

  if not moved:
    _write_state(args.state, state)
    _emit_outputs({"noop": "true"})
    print("nothing new upstream; no-op")
    return 0

  old_shas = submodules.read_submodule_shas(repo, old_master, submodules.FORK_SUBMODULES)
  new_shas = submodules.read_submodule_shas(repo, new_master, submodules.FORK_SUBMODULES)
  state["bumps"] = submodules.detect_bumps(old_shas, new_shas, submodules.FORK_SUBMODULES)

  gitops.create_trial_branch(repo, args.trial_branch, "master")
  rebase_status = gitops.rebase_tweaks(repo, old_master, NDM_TIP, args.trial_branch)
  state["rebase"] = rebase_status
  if rebase_status == "clean":
    # rebase left HEAD detached at the replayed tip; re-point the trial branch
    gitops.git(repo, "checkout", "-B", args.trial_branch, "HEAD")

  _write_state(args.state, state)
  _emit_outputs({
    "noop": "false",
    "rebase": rebase_status,
    "bumps": state["bumps"],
    "trial_branch": args.trial_branch,
  })
  print(f"prepared trial branch {args.trial_branch}: rebase={rebase_status}, bumps={state['bumps']}")
  return 0


def cmd_gate(args) -> int:
  state = json.loads(_read(args.state))
  report_text = _read(args.report) if os.path.exists(args.report) else ""
  decision = decision_for(state, ci_passed=args.ci_passed, report_text=report_text)
  _emit_outputs({"decision": decision})
  print(f"decision={decision}")
  return 0


def cmd_publish(args) -> int:
  gitops.force_publish(args.repo, args.trial_branch, TARGET_BRANCH)
  print(f"published {args.trial_branch} -> {TARGET_BRANCH}")
  return 0


def _write_state(path: str, state: dict) -> None:
  with open(path, "w") as f:
    json.dump(state, f, indent=2)


def _read(path: str) -> str:
  with open(path) as f:
    return f.read()


def _str2bool(v: str) -> bool:
  return str(v).strip().lower() in ("1", "true", "yes", "y")


def main(argv=None) -> int:
  parser = argparse.ArgumentParser(prog="ndm-sync")
  sub = parser.add_subparsers(dest="cmd", required=True)

  p = sub.add_parser("prepare")
  p.add_argument("--upstream-url", required=True)
  p.add_argument("--trial-branch", required=True)
  p.add_argument("--repo", default=".")
  p.add_argument("--state", default="sync-state.json")
  p.set_defaults(func=cmd_prepare)

  g = sub.add_parser("gate")
  g.add_argument("--ci-passed", type=_str2bool, required=True)
  g.add_argument("--report", default="sync-report.json")
  g.add_argument("--state", default="sync-state.json")
  g.set_defaults(func=cmd_gate)

  pub = sub.add_parser("publish")
  pub.add_argument("--trial-branch", required=True)
  pub.add_argument("--repo", default=".")
  pub.set_defaults(func=cmd_publish)

  args = parser.parse_args(argv)
  return args.func(args)


if __name__ == "__main__":
  sys.exit(main())
