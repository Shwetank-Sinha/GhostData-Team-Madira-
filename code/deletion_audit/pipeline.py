"""Ties the stages together: classify the request, resolve the person, build the ledger, plan the steps."""
from __future__ import annotations

from dataclasses import dataclass

from .classifier import baseline_authorizes_deletion
from .evidence import EvidenceIndex, build_index
from .identity import IdentityResolver
from .ledger import CaseLedger, build_ledger, relevant_resources
from .models import Dataset, DeletionRequest
from .planner import plan_steps
from .policy import Policy
from .readings import Readings
from .workflow import WorkflowLinks, link_through_workflow

NO_RESOURCE_NOTE = ("no resource could be identified from admissible evidence; "
                    "COMPLETE because no identifiable residue exists in it")


@dataclass(frozen=True, slots=True)
class Answer:
    """The result for one case."""
    case_id: str
    status: str
    steps: list
    ledger: CaseLedger | None
    note: str = ""      # why the case came out this way (classification reason, identity failure, ...)


class Pipeline:
    def __init__(self, dataset: Dataset, index: EvidenceIndex | None = None, use_readings: bool = True) -> None:
        self.dataset = dataset
        self.index = index or build_index(dataset)
        self.readings = Readings.load(self.index) if use_readings else Readings([])
        self.resolver = IdentityResolver(dataset.identities, dataset.audit_log)
        self.policy = Policy(dataset.rules)

        # Resources without any identifier are tied to cases through the activity log, and that
        # matching only works across all cases at once, so every request and sample goes in together.
        everyone = [*dataset.requests, *dataset.sample_requests]
        subjects = {r.case_id: self.resolver.resolve(r) for r in everyone}
        self._relevant = {r.case_id: relevant_resources(r, subjects[r.case_id], self.index)
                          for r in everyone if subjects[r.case_id].resolved}
        self.workflow: WorkflowLinks = link_through_workflow(everyone, dataset.activity, self.index,
                                                             self._relevant)

    def answer(self, request: DeletionRequest) -> Answer:
        authorizes, reason = baseline_authorizes_deletion(request.request_text)
        if not authorizes:
            return Answer(request.case_id, "NOT_APPLICABLE", [], None, reason)

        subject = self.resolver.resolve(request)
        if not subject.resolved:
            return Answer(request.case_id, "INCOMPLETE", [], None, f"identity not resolved: {subject.reason}")

        linked_account = self.workflow.account.get(request.case_id)
        ledger = build_ledger(request, subject, self.index, self.policy, (linked_account,) if linked_account else (),
                              self.readings)
        status, steps = plan_steps(ledger)
        return Answer(request.case_id, status, steps, ledger, reason if steps else NO_RESOURCE_NOTE)
