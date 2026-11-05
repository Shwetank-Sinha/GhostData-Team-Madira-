"""Row verifier: the checks every answer row has to pass before it can be written to output.csv."""
from __future__ import annotations

import json
from datetime import datetime

from .planner import OP_STATE, OPERATION_ORDER, PHASE_ORDER, RULES

STATUSES = ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE")
STEP_KEYS = ("step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id")

# Which phase each operation belongs to; OPERATION_ORDER lists findings, remediations, then verifications.
_PHASE_SLICES = (("FINDING", slice(0, 4)), ("REMEDIATION", slice(4, 9)), ("VERIFICATION", slice(9, None)))
PHASE_OF = {op: phase for phase, part in _PHASE_SLICES for op in OPERATION_ORDER[part]}


def _follow_ups() -> dict[str, tuple[set[str], set[str]]]:
    """For each finding: the remediations that may answer it and the verifications that must close it."""
    table: dict[str, tuple[set[str], set[str]]] = {}
    for finding, remediation, verification in RULES.values():
        if finding:
            fixes, checks = table.setdefault(finding, (set(), set()))
            fixes.add(remediation)
            checks.add(verification)
    return table


FOLLOW_UP = _follow_ups()


def _check_evidence(where: str, step: dict, status: str, audit_at: datetime, evidence_times: dict,
                    evidence_names: dict | None, evidence_systems: dict | None) -> list[str]:
    """Rules about the evidence_id of one step."""
    found: list[str] = []
    cited = step["evidence_id"]
    if status == "COMPLETE" and step["phase"] != "VERIFICATION":
        found.append(f"{where}: a COMPLETE row may only contain verification steps")
    if status == "INCOMPLETE" and step["phase"] != "FINDING" and cited != "":
        found.append(f"{where}: {step['phase']} step in an INCOMPLETE row must have an empty evidence_id")
    if not (status == "COMPLETE" or step["phase"] == "FINDING"):
        return found                      # future work cites nothing
    if not cited:
        found.append(f"{where}: {step['operation']} on {step['resource_id']} cites no evidence")
    elif cited not in evidence_times:
        found.append(f"{where}: unknown evidence id {cited}")
    elif evidence_times[cited] > audit_at:
        found.append(f"{where}: evidence {cited} is dated after audit_at")
    elif evidence_names is not None and cited in evidence_names:
        covers_system = (step["operation"] == "VERIFY_RECORD_ABSENT"
                         and step["system_id"] in (evidence_systems or {}).get(cited, ()))
        if step["resource_id"] not in evidence_names[cited] and not covers_system:
            found.append(f"{where}: evidence {cited} neither names {step['resource_id']} "
                         f"nor covers {step['system_id']}")
    return found


def _check_findings_are_closed(case_id: str, steps: list[dict]) -> list[str]:
    """Every finding needs a matching remediation and a closing verification on the same resource."""
    operations: dict[str, set[str]] = {}
    for step in steps:
        if step.get("operation") in OP_STATE:
            operations.setdefault(step["resource_id"], set()).add(step["operation"])
    found: list[str] = []
    for resource, ops in sorted(operations.items()):
        for finding in sorted(ops & set(FOLLOW_UP)):
            fixes, checks = FOLLOW_UP[finding]
            if not ops & fixes:
                found.append(f"{case_id}: {resource} has {finding} but no matching remediation")
            if not ops & checks:
                found.append(f"{case_id}: {resource} has {finding} but no closing verification")
    return found


def verify_row(case_id: str, status: str, steps: list[dict], audit_at: datetime,
               evidence_times: dict[str, datetime], allow_unidentified: bool = False,
               evidence_names: dict[str, set[str]] | None = None,
               evidence_systems: dict[str, set[str]] | None = None) -> list[str]:
    """Problems with one answer row; an empty list means the row is valid.

    evidence_times maps every citable id (file, activity or audit id) to when it was captured or happened.
    With evidence_names (file -> resource ids it names) and evidence_systems (file -> systems it covers)
    a cited file must also name the resource, or, for an absence check, cover the resource's system.
    """
    if status not in STATUSES:
        return [f"{case_id}: unknown status {status!r}"]
    if status == "NOT_APPLICABLE":
        return [f"{case_id}: NOT_APPLICABLE row must have an empty step list"] if steps else []

    problems: list[str] = []
    if not steps:
        if not allow_unidentified:
            problems.append(f"{case_id}: {status} row has no steps")
        elif status != "COMPLETE":
            problems.append(f"{case_id}: an unidentified case must be COMPLETE")

    last_key = None
    seen_keys: set[tuple] = set()
    for number, step in enumerate(steps, start=1):
        where = f"{case_id} step {number}"
        if set(step) != set(STEP_KEYS):
            problems.append(f"{where}: keys {sorted(step)} differ from the contract")
            continue
        if step["step_no"] != number:
            problems.append(f"{where}: step_no is {step['step_no']}")
        if step["operation"] not in OP_STATE:
            problems.append(f"{where}: unknown operation {step['operation']}")
            continue
        if PHASE_OF[step["operation"]] != step["phase"]:
            problems.append(f"{where}: operation {step['operation']} does not belong to phase {step['phase']}")
        if OP_STATE[step["operation"]] != step["state"]:
            problems.append(f"{where}: state {step['state']} does not fit {step['operation']}")
        key = (PHASE_ORDER[step["phase"]], OPERATION_ORDER.index(step["operation"]),
               step["system_id"], step["resource_id"])
        if last_key is not None and key < last_key:
            problems.append(f"{where}: out of order")
        last_key = key
        if key in seen_keys:
            problems.append(f"{where}: duplicate of an earlier step")
        seen_keys.add(key)
        problems += _check_evidence(where, step, status, audit_at, evidence_times, evidence_names, evidence_systems)

    if status == "INCOMPLETE":
        problems += _check_findings_are_closed(case_id, steps)
        if steps and not any(s.get("phase") == "FINDING" for s in steps):
            problems.append(f"{case_id}: INCOMPLETE row has no finding")
    return problems


def serialize_steps(steps: list[dict]) -> str:
    """Stable JSON for the steps_json column: fixed key order, no spaces, non-ASCII kept."""
    return json.dumps([{key: step[key] for key in STEP_KEYS} for step in steps],
                      ensure_ascii=False, separators=(",", ":"))
