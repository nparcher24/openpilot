import os
import re

from openpilot.tools.ndm.report import parse_report

PROMPT = os.path.join(os.path.dirname(__file__), "sync-prompt.md")


def _example_json() -> str:
  text = open(PROMPT).read()
  match = re.search(r"```json\n(.*?)\n```", text, re.DOTALL)
  assert match, "sync-prompt.md must contain a ```json example block"
  return match.group(1)


def test_prompt_example_matches_schema():
  report = parse_report(_example_json())
  assert report.status in ("clean", "resolved", "risky")
  assert report.confidence in ("high", "low")


def test_prompt_mentions_no_drop_rule():
  text = open(PROMPT).read().lower()
  assert "ndm:" in text
  assert "sync-report.json" in text
