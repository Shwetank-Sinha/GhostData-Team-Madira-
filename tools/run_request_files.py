"""Run request files through the engine and save the answers, with a comparison to expected outputs.

    python tools/run_request_files.py "Req 1.csv" "Req 2.csv" --out results --expected <folder with the Out files>

For each request file it writes "result_N.csv" (for a file called "req_N.csv"; other names get "<name>_result.csv")
in the same format as output.csv, in the file's own row order. A request the engine cannot answer is not
guessed: it goes into "result_N_skipped.csv" with the reason. A plain-words readable.md is always written, and
with --expected a comparison.md (the expected file for req_N.csv is out_N.csv).

How a request is answered (the same rules as the website):
  * a request that is not a deletion request is NOT_APPLICABLE, whoever the customer is
  * a deletion request needs a customer that exists in dataset/user_identities.csv; otherwise it is set aside
  * everything else goes through the full engine, in the context of the built-in requests, so linking that
    depends on the other requests works the same way as in the main run
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))
sys.path.insert(0, str(ROOT))

from deletion_audit.classifier import baseline_authorizes_deletion  # noqa: E402
from deletion_audit.data import load_dataset  # noqa: E402
from deletion_audit.evidence import build_index  # noqa: E402
from deletion_audit.identity import IdentityResolver  # noqa: E402
from deletion_audit.pipeline import Pipeline  # noqa: E402
from deletion_audit.runner import run_requests  # noqa: E402
from frontend.batches import parse_batch  # noqa: E402
from frontend.jobs import SKIP_REASONS  # noqa: E402

STEP_FIELDS = ("phase", "system_id", "resource_id", "operation", "state", "evidence_id")
GARBLED = re.compile(r"Ã.|â€|ã[\u0080-¿]|Â[\u0080-¿]")


def result_name(path: Path) -> str:
    """req_1.csv -> result_1.csv; any other name -> <name>_result.csv"""
    return re.sub(r"^req", "result", path.stem, flags=re.I) + ".csv" if re.match(r"(?i)req", path.stem) else f"{path.stem}_result.csv"


def number_of(path: Path) -> str | None:
    match = re.search(r"(\d+)\s*$", path.stem)
    return match.group(1) if match else None


def read_rows(path: Path) -> dict[str, tuple[str, list[dict]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return {r["case_id"]: (r["deletion_status"], json.loads(r["steps_json"] or "[]")) for r in csv.DictReader(handle)}


def steps_key(steps: list[dict]) -> list[tuple]:
    return [tuple(s.get(k, "") for k in STEP_FIELDS) for s in steps]


def describe(step: tuple) -> str:
    phase, system, resource, operation, state, evidence = step
    return f"{operation} on {resource} ({system})" + (f", citing {evidence}" if evidence else "")


def answer_file(path: Path, dataset, index, resolver, use_readings: bool) -> dict:
    parsed = parse_batch(path.read_bytes())
    out = {"file": path.name, "fatal": parsed["fatal"], "problems": parsed["problems"], "rows": [], "skipped": [],
           "garbled": [], "run_problems": [], "readings": 0}
    if parsed["fatal"]:
        return out
    requests = parsed["requests"]
    ids = {r.case_id for r in requests}
    practice = {r.case_id for r in dataset.sample_requests}
    answerable, answers = [], {}
    for r in requests:
        if GARBLED.search(r.request_text):
            out["garbled"].append(r.case_id)
        subject = resolver.resolve(r)
        if r.case_id in practice:
            out["skipped"].append((r, "This case id is already used by a built-in practice case."))
        elif subject.resolved:
            answerable.append(r)
        else:
            authorizes, _ = baseline_authorizes_deletion(r.request_text)
            if authorizes:
                reason = next((t for k, t in SKIP_REASONS if k in subject.reason), "We could not tell which customer this is.")
                out["skipped"].append((r, reason))
            else:
                answers[r.case_id] = ("NOT_APPLICABLE", "[]")      # not a deletion request: no customer needed

    if answerable:
        context = [r for r in dataset.requests if r.case_id not in ids] + answerable
        run_dataset = replace(dataset, requests=tuple(context))
        pipeline = Pipeline(run_dataset, index=index, use_readings=use_readings)
        outcome = run_requests(run_dataset, pipeline, answerable)
        out["run_problems"] = outcome.problems
        out["readings"] = len(pipeline.readings)
        answers.update({cid: (status, blob) for cid, status, blob in outcome.rows})

    skipped_ids = {r.case_id for r, _ in out["skipped"]}
    out["rows"] = [(r.case_id, *answers[r.case_id]) for r in requests if r.case_id in answers]
    out["requests"] = requests
    out["skipped_ids"] = skipped_ids
    return out


def compare(result: dict, expected: dict[str, tuple[str, list[dict]]]) -> list[dict]:
    got = {cid: (status, json.loads(blob)) for cid, status, blob in result["rows"]}
    skipped = {r.case_id: why for r, why in result["skipped"]}
    findings = []
    for case_id, (want_status, want_steps) in expected.items():
        if case_id in skipped:
            findings.append({"case": case_id, "kind": "not_produced", "want": want_status, "got": None, "why": skipped[case_id], "lines": []})
            continue
        if case_id not in got:
            findings.append({"case": case_id, "kind": "not_produced", "want": want_status, "got": None, "why": "not in the request file", "lines": []})
            continue
        status, steps = got[case_id]
        want_k, got_k = steps_key(want_steps), steps_key(steps)
        if status == want_status and want_k == got_k:
            kind, lines = "exact", []
        else:
            kind = "same_verdict" if status == want_status else "different_verdict"
            lines = [f"expected but missing: {describe(s)}" for s in want_k if s not in got_k]
            lines += [f"produced but not expected: {describe(s)}" for s in got_k if s not in want_k]
            if not lines and want_k != got_k:
                lines.append("the same steps, in a different order")
        findings.append({"case": case_id, "kind": kind, "want": want_status, "got": status, "why": "", "lines": lines})
    return findings


def write_outputs(result: dict, out_dir: Path, path: Path) -> list[Path]:
    written = []
    target = out_dir / result_name(path)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["case_id", "deletion_status", "steps_json"])
        writer.writerows(result["rows"])
    written.append(target)
    if result["skipped"]:
        skipped_path = out_dir / (target.stem + "_skipped.csv")
        with skipped_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(["case_id", "email", "reason"])
            writer.writerows([[r.case_id, r.email, why] for r, why in result["skipped"]])
        written.append(skipped_path)
    return written


VERDICTS = {"COMPLETE": "Really done", "INCOMPLETE": "Something is left", "NOT_APPLICABLE": "Not a deletion request"}
STEP_TEXT = {
    "REPORT_REMAINING_RECORD": "A record that should be gone is still there",
    "REPORT_EXPOSED_PII": "A kept record still shows personal details",
    "REPORT_ACTIVE_DATA_FLOW": "A process is still copying this person's data",
    "REPORT_RESTORE_RISK": "A backup could bring this data back",
    "DISABLE_DATA_FLOW": "Switch off the process that copies the data",
    "BLOCK_RESTORE": "Stop the backup from restoring this data",
    "DELETE_RECORD": "Delete the record",
    "REDACT_RECORD": "Blank out the personal details but keep the record",
    "ANONYMIZE_RECORD": "Scrub the record so it can't be linked to the person",
    "VERIFY_RECORD_ABSENT": "Check that the record is gone",
    "VERIFY_RECORD_PRESENT": "Check that the record we must keep is still there",
    "VERIFY_RECORD_REDACTED": "Check the personal details are blanked out",
    "VERIFY_RECORD_ANONYMIZED": "Check the record can no longer be linked to the person",
    "VERIFY_DATA_FLOW_DISABLED": "Check the copying process is switched off",
    "VERIFY_RESTORE_BLOCKED": "Check the data can't be restored",
}
PHASES = (("FINDING", "What was found"), ("REMEDIATION", "What to fix, in this order"), ("VERIFICATION", "How to check it afterwards"))


def readable_text(items: list[tuple[Path, dict, list[dict] | None]]) -> str:
    """The answers in plain words: what the engine produced for every request, one section per request."""
    lines = ["# What the engine produced, in plain words", "",
             "Every request from the request files, with the engine's answer written out step by step. "
             "The same answers, in the exact file format, are in the `result_*.csv` files.", ""]
    for path, result, _ in items:
        lines += [f"## {path.name}", ""]
        if result["fatal"]:
            lines += [f"The file could not be read: {result['fatal']}", ""]
            continue
        answers = {cid: (status, json.loads(blob)) for cid, status, blob in result["rows"]}
        skipped = {r.case_id: why for r, why in result["skipped"]}
        for request in result.get("requests", []):
            text = request.request_text if len(request.request_text) <= 220 else request.request_text[:217] + "..."
            if request.case_id in answers:
                status, steps = answers[request.case_id]
                lines += [f"### {request.case_id}: {VERDICTS[status]}", "", f"> {text}", "",
                          f"The company's system said: {request.reported_status.replace('_', ' ').lower()}.", ""]
                if not steps:
                    lines += ["No steps: " + ("nothing needs to be done." if status == "NOT_APPLICABLE" else "nothing identifiable to check."), ""]
                for phase, title in PHASES:
                    chosen = [s for s in steps if s["phase"] == phase]
                    if chosen:
                        lines += [f"**{title}**", ""]
                        lines += [f"{s['step_no']}. {STEP_TEXT.get(s['operation'], s['operation'])} — `{s['resource_id']}` ({s['system_id']})"
                                  + (f", based on `{s['evidence_id']}`" if s["evidence_id"] else "") for s in chosen]
                        lines.append("")
            elif request.case_id in skipped:
                lines += [f"### {request.case_id}: not answered", "", f"> {text}", "",
                          f"Set aside, not guessed. Reason: {skipped[request.case_id]}", ""]
    return "\n".join(lines)


def comparison_text(items: list[tuple[Path, dict, list[dict] | None]]) -> str:
    kinds = {"exact": "Matches the expected output exactly", "same_verdict": "Same verdict, steps differ",
             "different_verdict": "Different verdict", "not_produced": "Could not be answered"}
    lines = ["# Results compared with the expected outputs", "",
             "Each request file was run through the engine and its answer was compared with the matching expected file.", ""]
    total = {k: 0 for k in kinds}
    for path, result, findings in items:
        lines += [f"## {path.name}", ""]
        if result["fatal"]:
            lines += [f"The file could not be read: {result['fatal']}", ""]
            continue
        if result["problems"]:
            lines += ["Rows with problems (not run):"] + [f"* line {p['line']}: {p['message']}" for p in result["problems"]] + [""]
        if result["garbled"]:
            lines += [f"Note: the request text of {', '.join(result['garbled'])} contains garbled characters (it looks like the file "
                      "was saved with the wrong text encoding). The answer does not depend on it, but the original text is lost.", ""]
        if findings is None:
            lines += ["No expected file was found to compare with.", ""]
            continue
        lines += ["| Request | Expected | Got | Result |", "|---|---|---|---|"]
        for f in findings:
            total[f["kind"]] += 1
            lines.append(f"| {f['case']} | {f['want']} | {f['got'] or '-'} | {kinds[f['kind']]} |")
        lines.append("")
        for f in findings:
            if f["kind"] == "exact":
                continue
            lines.append(f"**{f['case']}** — {kinds[f['kind']]}.")
            if f["why"]:
                lines.append(f"Why: {f['why']}")
            lines += [f"* {t}" for t in f["lines"][:12]]
            if len(f["lines"]) > 12:
                lines.append(f"* …and {len(f['lines']) - 12} more differences")
            lines.append("")
    lines += ["## Summary", ""] + [f"* {label}: {total[k]}" for k, label in kinds.items()] + [""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+", type=Path, help="request CSV files")
    parser.add_argument("--out", type=Path, required=True, help="folder for the results")
    parser.add_argument("--expected", type=Path, help="folder holding the expected output files (Out N.csv)")
    parser.add_argument("--no-readings", action="store_true", help="ignore the stored screenshot readings")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    dataset = load_dataset()
    index = build_index(dataset)
    resolver = IdentityResolver(dataset.identities, dataset.audit_log)
    summary = []
    for path in args.files:
        result = answer_file(path, dataset, index, resolver, not args.no_readings)
        findings = None
        if args.expected and not result["fatal"]:
            number = number_of(path)
            match = next((p for p in sorted(args.expected.glob("*.csv")) if re.match(r"(?i)out", p.stem) and number_of(p) == number), None)
            if match:
                findings = compare(result, read_rows(match))
        written = [] if result["fatal"] else write_outputs(result, args.out, path)
        summary.append((path, result, findings))
        print(f"{path.name}: {len(result['rows'])} answered, {len(result['skipped'])} set aside"
              + (f" -> {', '.join(w.name for w in written)}" if written else f" (could not be read: {result['fatal']})"))
        for problem in result["run_problems"]:
            print("   engine check problem:", problem)
    (args.out / "readable.md").write_text(readable_text(summary), encoding="utf-8")
    print(f"plain-words version written to {args.out / 'readable.md'}")
    if args.expected:
        (args.out / "comparison.md").write_text(comparison_text(summary), encoding="utf-8")
        print(f"comparison written to {args.out / 'comparison.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
