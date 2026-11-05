"""Typed rows for the tables under dataset/, plus the bundle that holds them all."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DeletionRequest:
    """One case to audit (a row of deletion_requests.csv)."""
    case_id: str
    email: str
    requested_at: datetime
    reported_status: str      # what the deletion workflow claims, not what is true
    reported_at: datetime
    audit_at: datetime        # nothing dated after this may influence the answer
    request_text: str


@dataclass(frozen=True, slots=True)
class Identity:
    """A user as they are in the current snapshot."""
    user_id: str
    name: str
    email: str
    phone: str
    email_hash: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One logged change of an identity field."""
    audit_id: str
    user_id: str
    event_time: datetime
    field_name: str
    old_value: str
    new_value: str


@dataclass(frozen=True, slots=True)
class Activity:
    """One row of the global system activity stream."""
    activity_id: str
    event_time: datetime
    event_type: str
    source_system: str
    target_system: str
    resource_id: str
    reported_result: str
    details: str


@dataclass(frozen=True, slots=True)
class Rule:
    """The treatment required for one data category."""
    rule_id: str
    data_category: str
    condition: str
    required_action: str


@dataclass(frozen=True, slots=True)
class EvidenceFile:
    """A manifest entry for one evidence file."""
    file_id: str
    file_path: str
    origin: str
    captured_at: datetime
    abs_path: Path


@dataclass(frozen=True, slots=True)
class Dataset:
    """Everything loaded from dataset/."""
    root: Path
    requests: tuple[DeletionRequest, ...]
    sample_requests: tuple[DeletionRequest, ...]
    identities: tuple[Identity, ...]
    audit_log: tuple[AuditEvent, ...]
    activity: tuple[Activity, ...]
    rules: tuple[Rule, ...]
    evidence_files: tuple[EvidenceFile, ...]
    # case_id -> (deletion_status, steps). Only the evaluator reads this.
    sample_output: dict[str, tuple[str, list[dict]]] = field(default_factory=dict)
