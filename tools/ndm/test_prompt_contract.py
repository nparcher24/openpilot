import re
from pathlib import Path

from tools.ndm.report import parse_report  # noqa: TID251

PROMPT = Path(__file__).parent / "sync-prompt.md"


def _example_json() -> str:
  text = PROMPT.read_text()
  match = re.search(r"```json\n(.*?)\n```", text, re.DOTALL)
  assert match, "sync-prompt.md must contain a ```json example block"
  return match.group(1)


def test_prompt_example_matches_schema():
  report = parse_report(_example_json())
  assert report.status in ("clean", "resolved", "risky")
  assert report.confidence in ("high", "low")


def test_prompt_mentions_no_drop_rule():
  text = PROMPT.read_text().lower()
  assert "ndm:" in text
  assert "sync-report.json" in text
  assert "sync-report.md" in text
