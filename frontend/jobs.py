"""Running the engine for the website.

One job is one run of the engine over one batch of requests. A job reports its progress while it works,
saves its results and files under runs/web/<id>/, and can be reopened later (even after a restart).
"""
from __future__ import annotations

import csv
import io
import json
import threading
import time
import uuid
import zipfile
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from deletion_audit.classifier import baseline_authorizes_deletion
from deletion_audit.common import REPO_ROOT, case_sort_key
from deletion_audit.data import load_dataset
from deletion_audit.evaluation import write_report
from deletion_audit.evidence import build_index
from deletion_audit.identity import IdentityResolver
from deletion_audit.pipeline import Answer, Pipeline
from deletion_audit.readings import Readings
from deletion_audit.runner import run_requests
from deletion_audit.usage import write_usage_report

WEB_DIR = REPO_ROOT / "runs" / "web"
SUBMISSION_DIR = REPO_ROOT / "submission"
BUILTIN_ID = "builtin"

STAGES = [
    ("data", "Loading the data", 0.04),
    ("people", "Working out who each person is", 0.10),
    ("evidence", "Reading the evidence", 0.14),
    ("requests", "Checking every request", 0.56),
    ("practice", "Scoring on the practice cases", 0.10),
    ("reports", "Writing your results", 0.06),
]

FINDING_LABELS = {
    "REPORT_REMAINING_RECORD": ("record still there", "records still there"),
    "REPORT_EXPOSED_PII": ("record exposing personal details", "records exposing personal details"),
    "REPORT_ACTIVE_DATA_FLOW": ("process still copying data", "processes still copying data"),
    "REPORT_RESTORE_RISK": ("backup that could bring data back", "backups that could bring data back"),
}
SKIP_REASONS = (
    ("not held by any user", "This email is not in the customer list."),
    ("more than one user", "This email belongs to more than one customer, so we cannot tell who it is."),
    ("only became", "This email only became the customer's after the audit date."),
)


@dataclass
class Batch:
    id: str
    name: str
    requests: list
    problems: list
    total_rows: int
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    matched: int | None = None                  # how many requests belong to a customer in the data (None: not checked yet)
    unmatched: list = field(default_factory=list)   # the ones that do not, each with the reason

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "rows": len(self.requests), "total_rows": self.total_rows,
                "problems": len(self.problems), "created": self.created, "matched": self.matched,
                "unmatched_count": len(self.unmatched)}


@dataclass
class Job:
    id: str
    batch_id: str
    batch_name: str
    use_readings: bool
    state: str = "queued"                  # queued | running | done | error
    stage: int = 0
    stage_progress: float = 0.0            # 0..1 inside the current stage
    message: str = ""
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    seconds: float = 0.0
    result: dict | None = None

    def progress(self) -> float:
        before = sum(w for _, _, w in STAGES[:self.stage])
        current = STAGES[min(self.stage, len(STAGES) - 1)][2] * self.stage_progress
        return 1.0 if self.state == "done" else min(0.999, before + current)

    def public(self, full: bool = True) -> dict:
        out = {"id": self.id, "batch_id": self.batch_id, "batch_name": self.batch_name, "state": self.state,
               "stage": self.stage, "stage_label": STAGES[min(self.stage, len(STAGES) - 1)][1],
               "stages": [label for _, label, _ in STAGES], "progress": round(self.progress(), 4),
               "message": self.message, "created": self.created, "seconds": round(self.seconds, 2),
               "use_readings": self.use_readings}
        if self.result:
            if full:
                out["result"] = self.result
            else:
                out["counts"] = {k: self.result["totals"][k] for k in ("complete", "incomplete", "not_applicable")}
                out["ran"] = self.result.get("batch", {}).get("ran", 0)
        return out


class AppState:
    """Everything the server shares: the loaded data, the evidence index, uploaded batches and jobs."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.dataset = None
        self.index = None
        self.readings_count = 0
        self.ready = False
        self.error: str | None = None
        self.warm_seconds = 0.0
        self.batches: dict[str, Batch] = {}
        self.jobs: dict[str, Job] = {}
        self._reload_saved_jobs()

    # ------------------------------------------------------------------ start-up
    def warm_up(self) -> None:
        """Load the data and read all the evidence once (the slow part), so each run is quick."""
        started = time.time()
        try:
            dataset = load_dataset()
            index = build_index(dataset)
            with self.lock:
                self.dataset, self.index = dataset, index
                self.readings_count = len(Readings.load(index))
                self.batches[BUILTIN_ID] = Batch(BUILTIN_ID, "Built-in batch", list(dataset.requests), [],
                                                 len(dataset.requests), created="")
                self.ready = True
        except Exception as exc:                                   # shown on the page instead of crashing
            self.error = f"{type(exc).__name__}: {str(exc)[:300]}"
        self.warm_seconds = time.time() - started

    def _reload_saved_jobs(self) -> None:
        if not WEB_DIR.is_dir():
            return
        for folder in sorted(WEB_DIR.iterdir()):
            saved = folder / "job.json"
            if saved.is_file():
                try:
                    data = json.loads(saved.read_text(encoding="utf-8"))
                    job = Job(**{k: data[k] for k in ("id", "batch_id", "batch_name", "use_readings", "created",
                                                      "seconds", "result")}, state="done", stage=len(STAGES) - 1,
                              stage_progress=1.0)
                    self.jobs[job.id] = job
                except (KeyError, TypeError, json.JSONDecodeError):
                    continue

    # ------------------------------------------------------------------ batches
    def split_requests(self, requests: list, builtin: bool) -> tuple[list, list, list]:
        """Sort requests into: (checked by the engine, answered "not a deletion request", set aside with a reason).

        A request that is not a deletion request needs no customer, so it is answered whoever sent it. A deletion
        request needs a customer that exists in the data; without one it is set aside, never guessed.
        """
        dataset = self.dataset
        resolver = IdentityResolver(dataset.identities, dataset.audit_log)
        practice_ids = {r.case_id for r in dataset.sample_requests}
        kept, not_deletion, skipped = [], [], []
        for request in requests:
            subject = resolver.resolve(request)
            if not builtin and request.case_id in practice_ids:
                skipped.append({"case_id": request.case_id, "email": request.email,
                                "reason": "This case id is already used by a built-in practice case. Rename it."})
            elif subject.resolved:
                kept.append(request)
            else:
                authorizes, why = baseline_authorizes_deletion(request.request_text)
                if not authorizes:
                    not_deletion.append((request, why))
                else:
                    reason = next((text for key, text in SKIP_REASONS if key in subject.reason),
                                  "We could not tell which customer this is.")
                    skipped.append({"case_id": request.case_id, "email": request.email, "reason": reason})
        return kept, not_deletion, skipped

    def add_batch(self, name: str, parsed: dict) -> Batch:
        batch = Batch(uuid.uuid4().hex[:10], name, parsed["requests"], parsed["problems"], parsed["total_rows"])
        if self.ready:                                   # tell the person right away which requests can be checked
            kept, not_deletion, skipped = self.split_requests(batch.requests, builtin=False)
            batch.matched, batch.unmatched = len(kept) + len(not_deletion), skipped
        with self.lock:
            self.batches[batch.id] = batch
        return batch

    # ------------------------------------------------------------------ jobs
    def running_job(self) -> Job | None:
        with self.lock:
            return next((j for j in self.jobs.values() if j.state in ("queued", "running")), None)

    def start_job(self, batch_id: str, use_readings: bool) -> Job:
        with self.lock:
            batch = self.batches.get(batch_id)
            if batch is None:
                raise KeyError("That batch no longer exists. Upload it again.")
            job = Job(uuid.uuid4().hex[:10], batch.id, batch.name, use_readings)
            self.jobs[job.id] = job
        threading.Thread(target=self._run, args=(job, batch), daemon=True).start()
        return job

    def _set(self, job: Job, stage: int, progress: float = 0.0, message: str = "") -> None:
        job.stage, job.stage_progress = stage, progress
        if message:
            job.message = message

    def _run(self, job: Job, batch: Batch) -> None:
        started = time.time()
        job.state = "running"
        try:
            self._set(job, 0, 0.0)
            deadline = time.time() + 300
            while not self.ready and not self.error and time.time() < deadline:
                job.message = "Getting the evidence ready the first time (this can take a little while)..."
                time.sleep(0.3)
            if self.error or not self.ready:
                raise RuntimeError(self.error or "The evidence took too long to load.")
            dataset, index = self.dataset, self.index
            self._set(job, 0, 1.0)

            # who is each person? Requests we cannot match to a customer are set aside, not guessed.
            self._set(job, 1, 0.0)
            kept, not_deletion, skipped = self.split_requests(batch.requests, builtin=batch.id == BUILTIN_ID)
            self._set(job, 1, 1.0)
            if not kept and not not_deletion:
                job.result = {"batch": {"name": batch.name, "rows": len(batch.requests), "ran": 0},
                              "skipped": skipped, "totals": _empty_totals()}
                raise RuntimeError("None of these requests could be matched to a customer in the data.")

            self._set(job, 2, 0.0)
            run_dataset = replace(dataset, requests=tuple(kept))      # the engine's context holds only checkable requests
            pipeline = Pipeline(run_dataset, index=index, use_readings=job.use_readings)
            self._set(job, 2, 1.0)

            self._set(job, 3, 0.0)
            outcome = run_requests(run_dataset, pipeline, kept,
                                   on_progress=lambda done, total: self._set(job, 3, done / total))
            for request, why in not_deletion:                         # no customer needed to say "not a deletion request"
                outcome.answers[request.case_id] = Answer(request.case_id, "NOT_APPLICABLE", [], None, why)
                outcome.rows.append((request.case_id, "NOT_APPLICABLE", "[]"))
            outcome.rows.sort(key=lambda row: case_sort_key(row[0]))
            answered = kept + [request for request, _ in not_deletion]

            job_dir = WEB_DIR / job.id
            job_dir.mkdir(parents=True, exist_ok=True)
            self._set(job, 4, 0.0)
            report_dataset = replace(dataset, requests=tuple(answered))
            samples, checks, report_path = write_report(report_dataset, pipeline, directory=job_dir / "_tmp")
            self._set(job, 4, 1.0)

            self._set(job, 5, 0.0)
            problems = outcome.problems
            files: list[dict] = []
            if not problems:
                _write_csv(job_dir / "output.csv", outcome.rows)
                files.append(_file("output.csv", "output.csv", "The answer for every request", job_dir))
            report_path.replace(job_dir / "evaluation_report.md")
            usage_path = write_usage_report({}, len(answered), directory=job_dir / "_tmp")
            usage_path.replace(job_dir / "usage_report.md")
            (job_dir / "_tmp").rmdir()
            files.append(_file("evaluation_report.md", "Evaluation report", "How accurate the engine is", job_dir))
            files.append(_file("usage_report.md", "Usage report", "How much AI was used", job_dir))
            if skipped:
                _write_skipped(job_dir / "skipped_requests.csv", skipped)
                files.append(_file("skipped_requests.csv", "Skipped requests", "Requests set aside, with the reason",
                                   job_dir))
            files.append({"name": "all_outputs.zip", "label": "Everything (zip)", "description": "All files above in one download",
                          "size": sum(f["size"] for f in files)})

            requests_by_id = {r.case_id: r for r in answered}
            details = {cid: _detail(requests_by_id[cid], answer) for cid, answer in outcome.answers.items()}
            (job_dir / "cases.json").write_text(json.dumps(details, ensure_ascii=False), encoding="utf-8")

            job.result = _build_result(batch, answered, skipped, outcome, samples, checks, pipeline, problems, files,
                                       details, time.time() - started)
            job.seconds = time.time() - started
            (job_dir / "job.json").write_text(json.dumps({
                "id": job.id, "batch_id": job.batch_id, "batch_name": job.batch_name, "use_readings": job.use_readings,
                "created": job.created, "seconds": job.seconds, "result": job.result}, ensure_ascii=False),
                encoding="utf-8")
            self._set(job, len(STAGES) - 1, 1.0)
            job.state = "done"
        except Exception as exc:                                    # a failed run is shown, never a crash
            job.message = str(exc) if isinstance(exc, RuntimeError) else f"{type(exc).__name__}: {str(exc)[:300]}"
            job.seconds = time.time() - started
            job.state = "error"

    # ------------------------------------------------------------------ reading results back
    def job_case(self, job_id: str, case_id: str) -> dict | None:
        path = WEB_DIR / job_id / "cases.json"
        if job_id not in self.jobs or not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8")).get(case_id)


# ---------------------------------------------------------------------- helpers
def _empty_totals() -> dict:
    return {"complete": 0, "incomplete": 0, "not_applicable": 0, "steps": 0, "avg_steps": 0.0}


def _write_csv(path: Path, rows) -> None:
    scratch = path.with_name(path.name + ".partial")         # an interrupted run never leaves half a file
    with scratch.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["case_id", "deletion_status", "steps_json"])
        writer.writerows(rows)
    scratch.replace(path)


def _write_skipped(path: Path, skipped: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["case_id", "email", "reason"])
        writer.writerows([[s["case_id"], s["email"], s["reason"]] for s in skipped])


def _file(name: str, label: str, description: str, folder: Path) -> dict:
    return {"name": name, "label": label, "description": description, "size": (folder / name).stat().st_size}


def _headline(status: str, steps: list[dict]) -> str:
    if status == "NOT_APPLICABLE":
        return "Not a deletion request"
    found = Counter(s["operation"] for s in steps if s["phase"] == "FINDING")
    if status == "INCOMPLETE":
        parts = [f"{n} {FINDING_LABELS[op][0 if n == 1 else 1]}" for op, n in found.most_common() if op in FINDING_LABELS]
        return " · ".join(parts) or "Needs a closer look"
    return f"All clear · {len(steps)} check{'s' if len(steps) != 1 else ''}" if steps else "Nothing found to check"


def _detail(request, answer) -> dict:
    return {"case_id": request.case_id, "email": request.email, "status": answer.status,
            "reported_status": request.reported_status, "requested_at": request.requested_at.isoformat(),
            "reported_at": request.reported_at.isoformat(), "audit_at": request.audit_at.isoformat(),
            "request_text": request.request_text, "note": answer.note, "steps": answer.steps,
            "headline": _headline(answer.status, answer.steps)}


def _build_result(batch, kept, skipped, outcome, samples, checks, pipeline, problems, files, details, seconds) -> dict:
    counts = Counter(a.status for a in outcome.answers.values())
    all_steps = [s for d in details.values() for s in d["steps"]]
    ran = len(kept)
    findings = Counter(s["operation"] for s in all_steps if s["phase"] == "FINDING")
    fixes = Counter(s["operation"] for s in all_steps if s["phase"] == "REMEDIATION")
    systems = Counter(s["system_id"] for s in all_steps if s["phase"] == "FINDING")

    claimed = [r for r in kept if r.reported_status == "COMPLETE" and details[r.case_id]["status"] != "NOT_APPLICABLE"]
    claimed_wrong = [r for r in claimed if details[r.case_id]["status"] == "INCOMPLETE"]

    ordered = sorted(details.values(), key=lambda d: case_sort_key(d["case_id"]))
    return {
        "batch": {"name": batch.name, "rows": len(batch.requests), "ran": ran, "skipped": len(skipped),
                  "upload_problems": len(batch.problems)},
        "totals": {"complete": counts["COMPLETE"], "incomplete": counts["INCOMPLETE"],
                   "not_applicable": counts["NOT_APPLICABLE"], "steps": len(all_steps),
                   "avg_steps": round(len(all_steps) / ran, 2) if ran else 0.0},
        "claims": {"said_complete": len(claimed), "still_has_data": len(claimed_wrong)},
        "findings": [{"operation": op, "count": n} for op, n in findings.most_common()],
        "fixes": [{"operation": op, "count": n} for op, n in fixes.most_common()],
        "systems": [{"system": s, "count": n} for s, n in systems.most_common(8)],
        "practice": {"cases": samples["cases"], "status_correct": samples["status_correct"],
                     "exact": samples["cases_exact"], "precision": samples["full_steps"]["precision"],
                     "recall": samples["full_steps"]["recall"], "f1": samples["full_steps"]["f1"]},
        "attention": {"no_identifiable_resource": outcome.unidentified, "left_out": len(outcome.left_out),
                      "contract_problems": problems[:10], "contract_problem_count": len(problems),
                      "readings_available": len(pipeline.readings), "readings_used": checks["from_readings"]},
        "skipped": skipped[:200],
        "files": files,
        "cases": [{"id": d["case_id"], "status": d["status"], "reported": d["reported_status"],
                   "steps": len(d["steps"]), "headline": d["headline"], "email": d["email"]} for d in ordered],
        "seconds": round(seconds, 2),
    }


def build_zip(job_id: str, names: list[str]) -> bytes:
    """All of a job's output files in one zip, built in memory."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            path = WEB_DIR / job_id / name
            if path.is_file():
                archive.write(path, name)
    return buffer.getvalue()
