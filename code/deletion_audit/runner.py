"""Run a set of requests through the pipeline and check every answer row.

Both the command line (main.py) and the website (webapp/) use this, so they always give the same answers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .common import case_sort_key
from .models import Dataset, DeletionRequest
from .pipeline import NO_RESOURCE_NOTE, Answer, Pipeline
from .planner import _entry_ops
from .verify import serialize_steps, verify_row


@dataclass
class RunOutcome:
    rows: list[tuple[str, str, str]] = field(default_factory=list)          # (case_id, status, steps_json)
    problems: list[str] = field(default_factory=list)                       # answer-rule problems (should be empty)
    audit_trail: list[dict] = field(default_factory=list)                   # why each case came out as it did
    unidentified: list[str] = field(default_factory=list)                   # COMPLETE with no steps: nothing identifiable
    left_out: list[tuple[str, str, str]] = field(default_factory=list)      # (case, resource, why) linked but not answered
    answers: dict[str, Answer] = field(default_factory=dict)


def in_case_order(requests) -> list:
    return sorted(requests, key=lambda r: case_sort_key(r.case_id))


def citable_times(dataset: Dataset) -> dict:
    """When each citable id (file, activity, audit record) was captured or happened."""
    times = {f.file_id: f.captured_at for f in dataset.evidence_files}
    times.update({a.activity_id: a.event_time for a in dataset.activity})
    times.update({e.audit_id: e.event_time for e in dataset.audit_log})
    return times


def file_contents(index) -> tuple[dict, dict]:
    """Per file: the resource ids it names, and the systems it covers."""
    names: dict[str, set[str]] = {}
    for rec in index.records:
        bucket = names.setdefault(rec.file_id, set())
        bucket.update(rec.mentions)
        if rec.resource_id:
            bucket.add(rec.resource_id)
    systems: dict[str, set[str]] = {}
    for scope in index.scopes:
        if scope.system:
            systems.setdefault(scope.file_id, set()).add(scope.system)
    return names, systems


def run_requests(dataset: Dataset, pipeline: Pipeline, requests: list[DeletionRequest],
                 on_progress: Callable[[int, int], None] | None = None) -> RunOutcome:
    """Answer every request in case order and check each row against the answer rules."""
    times = citable_times(dataset)
    names, systems = file_contents(pipeline.index)
    outcome = RunOutcome()
    ordered = in_case_order(requests)

    for position, request in enumerate(ordered, start=1):
        answer = pipeline.answer(request)
        ledger = answer.ledger
        is_unidentified = answer.status == "COMPLETE" and not answer.steps and answer.note == NO_RESOURCE_NOTE
        if is_unidentified:
            outcome.unidentified.append(request.case_id)
        outcome.problems += verify_row(request.case_id, answer.status, answer.steps, request.audit_at, times,
                                       allow_unidentified=is_unidentified, evidence_names=names,
                                       evidence_systems=systems)
        outcome.rows.append((request.case_id, answer.status, serialize_steps(answer.steps)))
        outcome.answers[request.case_id] = answer

        entries = ledger.entries if ledger else ()
        unplanned = [e for e in entries if _entry_ops(e) is None]
        outcome.audit_trail.append({
            "case_id": request.case_id, "status": answer.status, "note": answer.note,
            "user_id": ledger.subject.user_id if ledger else None,
            "entries": [{"resource_id": e.resource_id, "system_id": e.system_id, "state": e.state,
                         "evidence_id": e.evidence_id, "inferred": e.inferred} for e in entries],
            "workflow_account": pipeline.workflow.account.get(request.case_id),
            "dropped": [list(d) for d in (ledger.dropped if ledger else ())],
            "unplanned": [e.resource_id for e in unplanned],
        })
        if ledger:
            outcome.left_out += [(request.case_id, rid, why) for rid, why in ledger.dropped]
            outcome.left_out += [(request.case_id, e.resource_id, f"{e.action}/{e.state} has no allowed operation")
                                 for e in unplanned]
        if on_progress is not None:
            on_progress(position, len(ordered))
    return outcome
