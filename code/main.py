"""Command line entry point.

From the project root:
    python code/main.py run                   answer every request, write output.csv and the evaluation report
    python code/main.py run --output PATH     write the answers somewhere else
    python code/main.py run --no-report       write output.csv only
    python code/main.py identities            check that every request email resolves to a user
    python code/main.py index                 index all evidence files and print a summary
    python code/main.py serve                 open the website (run checks, upload batches, download results)
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deletion_audit.common import REPO_ROOT  # noqa: E402
from deletion_audit.data import DatasetError, load_dataset  # noqa: E402
from deletion_audit.evaluation import write_report  # noqa: E402
from deletion_audit.evidence import EvidenceIndexError, build_index  # noqa: E402
from deletion_audit.identity import IdentityResolver  # noqa: E402
from deletion_audit.pipeline import Pipeline  # noqa: E402
from deletion_audit.readings import ReadingsError  # noqa: E402
from deletion_audit.runner import in_case_order, run_requests  # noqa: E402
from deletion_audit.usage import write_usage_report  # noqa: E402

RUNS_DIR = REPO_ROOT / "runs"


def command_identities(_args: argparse.Namespace) -> int:
    try:
        dataset = load_dataset()
    except DatasetError as exc:
        print(exc, file=sys.stderr)
        return 2
    resolver = IdentityResolver(dataset.identities, dataset.audit_log)
    RUNS_DIR.mkdir(exist_ok=True)
    unresolved_total = 0
    for label, requests in (("requests", dataset.requests), ("samples", dataset.sample_requests)):
        subjects = [resolver.resolve(r) for r in in_case_order(requests)]
        tally = Counter((s.resolution, s.match_kind) for s in subjects)
        unresolved = [s.case_id for s in subjects if not s.resolved]
        unresolved_total += len(unresolved)
        print(f"{label}: {len(subjects)} cases, "
              + ", ".join(f"{res}/{kind}={n}" for (res, kind), n in sorted(tally.items(), key=str)))
        if unresolved:
            print(f"  unresolved: {unresolved[:10]}")
        if label == "requests":
            with (RUNS_DIR / "identity_resolution.csv").open("w", newline="", encoding="utf-8") as handle:
                out = csv.writer(handle)
                out.writerow(["case_id", "resolution", "user_id", "match_kind", "alias_count", "anomalies"])
                for s in subjects:
                    out.writerow([s.case_id, s.resolution, s.user_id, s.match_kind, len(s.aliases),
                                  "; ".join(s.anomalies)])
    mismatches = resolver.hash_anomalies()
    for line in mismatches[:10]:
        print("  hash mismatch: " + line, file=sys.stderr)
    return 1 if (mismatches or unresolved_total) else 0


def command_index(_args: argparse.Namespace) -> int:
    try:
        dataset = load_dataset()
        index = build_index(dataset)
    except (DatasetError, EvidenceIndexError) as exc:
        print(exc, file=sys.stderr)
        return 2
    by_kind = Counter(r.kind for r in index.records)
    summary = {
        "evidence_files": len(dataset.evidence_files), "files_indexed": len(index.files),
        "records": len(index.records), "records_by_kind": dict(sorted(by_kind.items())),
        "scopes": len(index.scopes), "prefix_system": dict(sorted(index.prefix_system.items())),
        "prefix_conflicts": {k: sorted(v) for k, v in index.prefix_conflicts.items()},
    }
    RUNS_DIR.mkdir(exist_ok=True)
    (RUNS_DIR / "evidence_index_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"indexed {summary['files_indexed']}/{summary['evidence_files']} files into "
          f"{summary['records']} records and {summary['scopes']} scopes")
    print("records by kind: " + ", ".join(f"{k}={v}" for k, v in summary["records_by_kind"].items()))
    print(f"prefix to system conflicts: {len(index.prefix_conflicts)}")
    return 1 if index.prefix_conflicts else 0


def command_run(args: argparse.Namespace) -> int:
    """Answer every request, verify every row, then write output.csv."""
    try:
        dataset = load_dataset()
        pipeline = Pipeline(dataset, use_readings=not args.no_readings)
    except (DatasetError, EvidenceIndexError, ReadingsError) as exc:
        print(exc, file=sys.stderr)
        return 2

    outcome = run_requests(dataset, pipeline, list(dataset.requests))
    rows, problems, audit_trail = outcome.rows, outcome.problems, outcome.audit_trail
    unidentified, left_out = outcome.unidentified, outcome.left_out

    RUNS_DIR.mkdir(exist_ok=True)
    (RUNS_DIR / "audit.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in audit_trail) + "\n",
        encoding="utf-8")

    if problems:
        print(f"{len(problems)} contract problems; output.csv not written", file=sys.stderr)
        for line in problems[:20]:
            print("  " + line, file=sys.stderr)
        return 1

    destination = Path(args.output) if args.output else REPO_ROOT / "output.csv"
    scratch = destination.with_name(destination.name + ".partial")   # an interrupted run never leaves half a file
    with scratch.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["case_id", "deletion_status", "steps_json"])
        writer.writerows(rows)
    scratch.replace(destination)

    by_status = Counter(status for _, status, _ in rows)
    step_total = sum(len(json.loads(blob)) for _, _, blob in rows)
    print(f"wrote {len(rows)} rows to {destination.name}: {dict(sorted(by_status.items()))}, "
          f"{step_total} steps, 0 contract problems")
    print(f"screenshot readings loaded: {len(pipeline.readings)}")
    print(f"workflow account links: {pipeline.workflow.stats}")
    print(f"resources linked to a case but left out of its answer: {len(left_out)} "
          "(see runs/audit.jsonl, fields dropped and unplanned)")
    print(f"cases with no identifiable resource (COMPLETE, no steps): {len(unidentified)} {unidentified}")
    if not args.no_report:
        samples, _, report_path = write_report(dataset, pipeline)
        print(f"samples: status {samples['status_correct']}/{samples['cases']}, exact {samples['cases_exact']}/{samples['cases']}, "
              f"F1 {samples['full_steps']['f1']}")
        print(f"report written to {report_path.relative_to(REPO_ROOT)}")
        usage_path = write_usage_report({}, len(dataset.requests))    # this run calls no model, so the ledger is empty
        print(f"usage report written to {usage_path.relative_to(REPO_ROOT)}")
    return 0


def command_serve(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(REPO_ROOT))      # the website lives in frontend/, next to code/
    from frontend.server import serve       # imported here so the other commands never need the website code
    return serve(port=args.port, open_browser=not args.no_browser)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="main.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("identities", help="check that every request email resolves to a user")
    commands.add_parser("index", help="index all evidence files")
    run = commands.add_parser("run", help="answer every request and write output.csv")
    run.add_argument("--output", help="write here instead of ./output.csv")
    run.add_argument("--no-report", action="store_true", help="skip writing the evaluation report")
    run.add_argument("--no-readings", action="store_true", help="ignore the stored screenshot readings")
    serve = commands.add_parser("serve", help="open the website (run checks, upload batches, download results)")
    serve.add_argument("--port", type=int, default=8000, help="port to listen on (default 8000)")
    serve.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    args = parser.parse_args(argv)
    return {"identities": command_identities, "index": command_index, "run": command_run,
            "serve": command_serve}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
