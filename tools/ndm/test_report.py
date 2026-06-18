import pytest

from openpilot.tools.ndm.report import Flag, SyncReport, parse_report, ReportError


def test_parse_minimal_clean_report():
    report = parse_report('{"status": "clean", "confidence": "high", "summary": "ok"}')
    assert report.status == "clean"
    assert report.confidence == "high"
    assert report.summary == "ok"
    assert report.flags == []


def test_parse_report_with_flags():
    text = (
        '{"status": "resolved", "confidence": "high", "summary": "done",'
        ' "flags": [{"type": "semantic", "file": "a.py", "detail": "api moved"}]}'
    )
    report = parse_report(text)
    assert report.flags == [Flag(type="semantic", file="a.py", detail="api moved")]


def test_round_trip_to_json():
    report = SyncReport(status="risky", confidence="low", summary="hmm", flags=[])
    assert parse_report(report.to_json()) == report


def test_invalid_json_raises():
    with pytest.raises(ReportError):
        parse_report("not json")


def test_unknown_status_raises():
    with pytest.raises(ReportError):
        parse_report('{"status": "weird", "confidence": "high", "summary": "x"}')


def test_unknown_confidence_raises():
    with pytest.raises(ReportError):
        parse_report('{"status": "clean", "confidence": "maybe", "summary": "x"}')


def test_missing_field_raises():
    with pytest.raises(ReportError):
        parse_report('{"status": "clean", "summary": "x"}')


def test_malformed_flag_raises():
    with pytest.raises(ReportError):
        parse_report('{"status": "clean", "confidence": "high", "summary": "x",'
                     ' "flags": [{"type": "semantic"}]}')


def test_non_dict_top_level_raises():
    with pytest.raises(ReportError):
        parse_report("[]")
    with pytest.raises(ReportError):
        parse_report("5")


def test_non_dict_flag_entry_raises():
    with pytest.raises(ReportError):
        parse_report('{"status": "clean", "confidence": "high", "summary": "x",'
                     ' "flags": [42]}')
