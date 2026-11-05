"""Load and validate the CSV tables in dataset/.

Every problem found is collected and raised together as one DatasetError, so a damaged
dataset can never be used half-way.
"""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Callable

from .common import DATASET_DIR, parse_ts
from .models import (
    Activity, AuditEvent, Dataset, DeletionRequest, EvidenceFile, Identity, Rule,
)

REPORTED_STATUSES = {"COMPLETE", "PARTIALLY_COMPLETE", "NOT_STARTED"}
AUDITED_FIELDS = {"email", "email_hash", "phone"}
RULE_ACTIONS = {"DELETE", "REDACT", "ANONYMIZE", "RETAIN"}

_REQUEST_COLUMNS = ("case_id", "email", "requested_at", "reported_status", "reported_at", "audit_at", "request_text")
EXPECTED_COLUMNS: dict[str, tuple[str, ...]] = {
    "deletion_requests.csv": _REQUEST_COLUMNS,
    "sample_deletion_requests.csv": _REQUEST_COLUMNS,
    "sample_output.csv": ("case_id", "deletion_status", "steps_json"),
    "user_identities.csv": ("user_id", "name", "email", "phone", "email_hash", "updated_at"),
    "user_audit_log.csv": ("audit_id", "user_id", "event_time", "field_name", "old_value", "new_value"),
    "system_activity.csv": ("activity_id", "event_time", "event_type", "source_system", "target_system",
                            "resource_id", "reported_result", "details"),
    "deletion_rules.csv": ("rule_id", "data_category", "condition", "required_action"),
    "evidence_files.csv": ("file_id", "file_path", "origin", "captured_at"),
}


class DatasetError(Exception):
    """Every validation problem found in the dataset, one per line."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        text = "\n".join(problems[:25])
        if len(problems) > 25:
            text += f"\n... and {len(problems) - 25} more"
        super().__init__("dataset validation failed:\n" + text)


class _Reader:
    """Reads tables from one folder and remembers the problems it meets."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.problems: list[str] = []

    def rows(self, name: str) -> list[dict[str, str]]:
        path = self.root / name
        if not path.is_file():
            self.problems.append(f"{name}: file not found at {path}")
            return []
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            header = tuple(reader.fieldnames or ())
            if header != EXPECTED_COLUMNS[name]:
                self.problems.append(f"{name}: header {header} != expected {EXPECTED_COLUMNS[name]}")
                return []
            return list(reader)

    def records(self, name: str, key: str, make: Callable[[dict[str, str]], object]) -> tuple:
        """Turn each row into a record, skipping (and reporting) empty or repeated ids and bad rows."""
        kept, used_ids = [], set()
        for line_no, row in enumerate(self.rows(name), start=2):   # the header is line 1
            ident = row.get(key, "")
            if not ident:
                self.problems.append(f"{name}:{line_no}: empty {key}")
            elif ident in used_ids:
                self.problems.append(f"{name}:{line_no}: duplicate {key} {ident!r}")
            else:
                used_ids.add(ident)
                try:
                    kept.append(make(row))
                except (ValueError, KeyError) as exc:
                    self.problems.append(f"{name}:{line_no}: {ident}: {exc}")
        return tuple(kept)


def _make_request(row: dict[str, str]) -> DeletionRequest:
    if row["reported_status"] not in REPORTED_STATUSES:
        raise ValueError(f"bad reported_status {row['reported_status']!r}")
    return DeletionRequest(row["case_id"], row["email"], parse_ts(row["requested_at"]), row["reported_status"],
                           parse_ts(row["reported_at"]), parse_ts(row["audit_at"]), row["request_text"])


def _make_identity(row: dict[str, str]) -> Identity:
    return Identity(row["user_id"], row["name"], row["email"], row["phone"], row["email_hash"],
                    parse_ts(row["updated_at"]))


def _make_audit_event(row: dict[str, str]) -> AuditEvent:
    if row["field_name"] not in AUDITED_FIELDS:
        raise ValueError(f"bad field_name {row['field_name']!r}")
    return AuditEvent(row["audit_id"], row["user_id"], parse_ts(row["event_time"]), row["field_name"],
                      row["old_value"], row["new_value"])


def _make_activity(row: dict[str, str]) -> Activity:
    return Activity(row["activity_id"], parse_ts(row["event_time"]), row["event_type"], row["source_system"],
                    row["target_system"], row["resource_id"], row["reported_result"], row["details"])


def _make_rule(row: dict[str, str]) -> Rule:
    if row["required_action"] not in RULE_ACTIONS:
        raise ValueError(f"bad required_action {row['required_action']!r}")
    return Rule(row["rule_id"], row["data_category"], row["condition"], row["required_action"])


def load_dataset(dataset_dir: Path | None = None) -> Dataset:
    """Load every table in dataset/ and check them against each other.

    sample_output.csv is read only because the evaluator needs it; nothing that produces
    predictions may look at Dataset.sample_output.
    """
    root = (dataset_dir or DATASET_DIR).resolve()
    reader = _Reader(root)

    requests = reader.records("deletion_requests.csv", "case_id", _make_request)
    samples = reader.records("sample_deletion_requests.csv", "case_id", _make_request)
    identities = reader.records("user_identities.csv", "user_id", _make_identity)
    audit_log = reader.records("user_audit_log.csv", "audit_id", _make_audit_event)
    activity = reader.records("system_activity.csv", "activity_id", _make_activity)
    rules = reader.records("deletion_rules.csv", "rule_id", _make_rule)
    evidence = reader.records(
        "evidence_files.csv", "file_id",
        lambda row: EvidenceFile(row["file_id"], row["file_path"], row["origin"], parse_ts(row["captured_at"]),
                                 root / row["file_path"]))

    problems = reader.problems
    known_users = {i.user_id for i in identities}
    problems += [f"user_audit_log.csv: {e.audit_id}: unknown user {e.user_id}"
                 for e in audit_log if e.user_id not in known_users]
    for item in evidence:
        # Lexical containment: blocks "../" paths but still allows a symlinked evidence folder.
        if not Path(os.path.normpath(item.abs_path)).is_relative_to(root):
            problems.append(f"evidence_files.csv: {item.file_id}: path leaves the dataset folder")
        elif not item.abs_path.is_file():
            problems.append(f"evidence_files.csv: {item.file_id}: missing file {item.file_path}")
    shared = {r.case_id for r in requests} & {r.case_id for r in samples}
    if shared:
        problems.append(f"case ids present in both requests and samples: {sorted(shared)[:5]}")

    sample_output: dict[str, tuple[str, list[dict]]] = {}
    for line_no, row in enumerate(reader.rows("sample_output.csv"), start=2):
        try:
            sample_output[row["case_id"]] = (row["deletion_status"], json.loads(row["steps_json"]))
        except json.JSONDecodeError as exc:
            problems.append(f"sample_output.csv:{line_no}: {row['case_id']}: bad steps_json ({exc})")

    if problems:
        raise DatasetError(problems)
    return Dataset(root=root, requests=requests, sample_requests=samples, identities=identities,
                   audit_log=audit_log, activity=activity, rules=rules, evidence_files=evidence,
                   sample_output=sample_output)
