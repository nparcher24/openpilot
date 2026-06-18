from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

VALID_STATUS = {"clean", "resolved", "risky"}
VALID_CONFIDENCE = {"high", "low"}


class ReportError(ValueError):
  """Raised when sync-report.json is missing, malformed, or out of contract."""


@dataclass
class Flag:
  type: str
  file: str
  detail: str


@dataclass
class SyncReport:
  status: str
  confidence: str
  summary: str
  flags: list[Flag] = field(default_factory=list)

  def to_json(self) -> str:
    return json.dumps(asdict(self), indent=2)


def parse_report(text: str) -> SyncReport:
  try:
    data = json.loads(text)
  except json.JSONDecodeError as e:
    raise ReportError(f"sync-report.json is not valid JSON: {e}") from e

  for key in ("status", "confidence", "summary"):
    if key not in data:
      raise ReportError(f"missing required field: {key}")
  if data["status"] not in VALID_STATUS:
    raise ReportError(f"invalid status: {data['status']!r}")
  if data["confidence"] not in VALID_CONFIDENCE:
    raise ReportError(f"invalid confidence: {data['confidence']!r}")

  flags = []
  for f in data.get("flags", []):
    if not all(k in f for k in ("type", "file", "detail")):
      raise ReportError(f"flag missing required keys: {f}")
    flags.append(Flag(type=f["type"], file=f["file"], detail=f["detail"]))

  return SyncReport(
    status=data["status"],
    confidence=data["confidence"],
    summary=data["summary"],
    flags=flags,
  )
