"""Stored readings of console screenshots: states that a viewer read off the page and wrote down.

OCR turns a console screenshot into text but cannot always tell what state a resource is in ("Ready",
"Continuous sync"). A reading supplies that state. It is checked by code before it is used, and it can only
fill in the state of a resource that identifiers already tie to a case; it never creates the link.

Checks at load time (a failure stops the run, so a bad file can never quietly change an answer):
  * the file is in the evidence manifest
  * the resource id really appears in that file's text
  * the resource type is known and the state is one the engine understands
At use time a reading counts only for a case audited at or after the file's capture time and, when the page
states an expiry (valid_until), no later than that.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .common import REPO_ROOT, parse_ts
from .evidence import EvidenceIndex
from .state import Observation

DEFAULT_PATH = REPO_ROOT / "code" / "readings" / "screenshot_readings.json"
KNOWN_STATES = {"PRESENT", "ABSENT", "IDENTIFIABLE", "ANONYMIZED", "REDACTED", "ACTIVE", "DISABLED", "BLOCKED"}


class ReadingsError(Exception):
    """The readings file does not agree with the evidence."""


@dataclass(frozen=True, slots=True)
class Reading:
    file_id: str
    resource_id: str
    state: str
    valid_until: datetime | None
    quote: str


class Readings:
    def __init__(self, items: list[Reading]) -> None:
        self._by_resource: dict[str, list[Reading]] = {}
        for item in items:
            self._by_resource.setdefault(item.resource_id, []).append(item)

    def __len__(self) -> int:
        return sum(len(v) for v in self._by_resource.values())

    @classmethod
    def load(cls, index: EvidenceIndex, path: Path = DEFAULT_PATH) -> "Readings":
        """Read and check the file; a missing file simply means no readings."""
        if not path.is_file():
            return cls([])
        raw = json.loads(path.read_text(encoding="utf-8"))
        items: list[Reading] = []
        problems: list[str] = []
        for entry in raw.get("readings", []):
            file_id, resource_id, state = entry.get("file_id", ""), entry.get("resource_id", ""), entry.get("state", "")
            where = f"{file_id}/{resource_id}"
            if file_id not in index.file_times:
                problems.append(f"{where}: file is not in the evidence manifest")
            elif not any(rec.file_id == file_id for rec in index.for_resource(resource_id)):
                problems.append(f"{where}: the resource id does not appear in that file")
            if index.system_of(resource_id) is None:
                problems.append(f"{where}: unknown resource type")
            if state not in KNOWN_STATES:
                problems.append(f"{where}: unknown state {state!r}")
            if not entry.get("quote"):
                problems.append(f"{where}: no quote from the page")
            until = entry.get("valid_until")
            items.append(Reading(file_id, resource_id, state, parse_ts(until) if until else None,
                                 entry.get("quote", "")))
        if problems:
            raise ReadingsError("readings do not match the evidence:\n" + "\n".join(problems))
        return cls(items)

    def observations_for(self, resource_id: str, index: EvidenceIndex, audit_at: datetime) -> list[Observation]:
        """What the stored readings say about one resource, for a case audited at `audit_at`."""
        out: list[Observation] = []
        for item in self._by_resource.get(resource_id, ()):
            captured = index.file_times[item.file_id]
            if captured > audit_at or (item.valid_until is not None and audit_at > item.valid_until):
                continue
            out.append(Observation(resource_id, item.state, captured, item.file_id, captured,
                                   "screen_reading", "reading", ""))
        return out
