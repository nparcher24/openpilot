from tools.ndm.gate import decide  # noqa: TID251
from tools.ndm.report import Flag, SyncReport  # noqa: TID251


def _ok_report():
  return SyncReport(status="clean", confidence="high", summary="ok", flags=[])


def test_publishes_when_everything_green():
  assert decide(ci_passed=True, report=_ok_report(), submodule_bumps=[]) == "publish"


def test_publishes_on_resolved_high_confidence():
  report = SyncReport(status="resolved", confidence="high", summary="ok", flags=[])
  assert decide(ci_passed=True, report=report, submodule_bumps=[]) == "publish"


def test_escalates_when_ci_fails():
  assert decide(ci_passed=False, report=_ok_report(), submodule_bumps=[]) == "escalate"


def test_escalates_on_submodule_bump():
  assert decide(ci_passed=True, report=_ok_report(), submodule_bumps=["opendbc"]) == "escalate"


def test_escalates_on_risky_status():
  report = SyncReport(status="risky", confidence="high", summary="x", flags=[])
  assert decide(ci_passed=True, report=report, submodule_bumps=[]) == "escalate"


def test_escalates_on_low_confidence():
  report = SyncReport(status="resolved", confidence="low", summary="x", flags=[])
  assert decide(ci_passed=True, report=report, submodule_bumps=[]) == "escalate"


def test_escalates_when_flags_present():
  report = SyncReport(status="clean", confidence="high", summary="x",
                      flags=[Flag(type="semantic", file="a.py", detail="api moved")])
  assert decide(ci_passed=True, report=report, submodule_bumps=[]) == "escalate"
