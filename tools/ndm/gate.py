from __future__ import annotations

from openpilot.tools.ndm.report import SyncReport

PUBLISHABLE_STATUS = {"clean", "resolved"}


def decide(*, ci_passed: bool, report: SyncReport, submodule_bumps: list[str]) -> str:
  """Return 'publish' only when every safety gate is satisfied, else 'escalate'."""
  if not ci_passed:
    return "escalate"
  if submodule_bumps:
    return "escalate"
  if report.status not in PUBLISHABLE_STATUS:
    return "escalate"
  if report.confidence != "high":
    return "escalate"
  if report.flags:
    return "escalate"
  return "publish"
