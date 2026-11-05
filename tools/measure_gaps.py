"""Where do the engine's gaps show up in the evidence? Read-only; changes nothing.

For every reference step the engine misses on the public samples, and every resource it drops on the
evaluation requests, list which kinds of evidence mention the resource (and whether they predate audit_at).
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from deletion_audit.common import case_sort_key  # noqa: E402
from deletion_audit.data import load_dataset  # noqa: E402
from deletion_audit.pipeline import Pipeline  # noqa: E402

KIND_GROUP = {"sql_row": "sql", "json_record": "json", "log_line": "log", "log_trace": "log",
              "text_line": "text", "document": "pdf/png", "document_line": "pdf/png"}


def mentions(index, resource_id, audit_at):
    """kind group -> (records, records dated by audit_at)"""
    out = defaultdict(lambda: [0, 0])
    for rec in index.for_resource(resource_id):
        g = KIND_GROUP.get(rec.kind, rec.kind)
        out[g][0] += 1
        when = rec.record_time or rec.captured_at
        if when <= audit_at and rec.captured_at <= audit_at:
            out[g][1] += 1
    return {k: tuple(v) for k, v in out.items()}


def describe(m):
    return ", ".join(f"{k} {v[1]}/{v[0]}" for k, v in sorted(m.items())) or "no evidence mentions it"


def main():
    dataset = load_dataset()
    pipe = Pipeline(dataset)
    index = pipe.index
    act_by_res = defaultdict(list)
    for a in dataset.activity:
        act_by_res[a.resource_id].append(a)

    print("=== 1. Reference steps the engine misses on the 32 samples")
    miss_rows, group_tally = [], Counter()
    for req in sorted(dataset.sample_requests, key=lambda r: case_sort_key(r.case_id)):
        gold_status, gold_steps = dataset.sample_output[req.case_id]
        ans = pipe.answer(req)
        have = {(s["operation"], s["resource_id"]) for s in ans.steps}
        for s in gold_steps:
            if (s["operation"], s["resource_id"]) in have:
                continue
            m = mentions(index, s["resource_id"], req.audit_at)
            admissible_groups = sorted(k for k, v in m.items() if v[1] > 0)
            acts = act_by_res.get(s["resource_id"], [])
            miss_rows.append((req.case_id, s["operation"], s["resource_id"], s["evidence_id"], m, len(acts)))
            group_tally["any admissible evidence mention" if admissible_groups else "no admissible evidence mention"] += 1
            if "pdf/png" in admissible_groups:
                group_tally["... of which in PDF/PNG"] += 1
            print(f"{req.case_id:8} {s['operation']:26} {s['resource_id']:16} gold_evidence={s['evidence_id']:12} "
                  f"mentions: {describe(m)}; activity rows: {len(acts)}")
    print(dict(group_tally))

    print("\n=== 2. Resources linked to an evaluation case but left out of its answer")
    audit = [json.loads(line) for line in (ROOT / "runs" / "audit.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    reqs = {r.case_id: r for r in dataset.requests}
    reasons, kinds = Counter(), Counter()
    for a in audit:
        for rid, why in a["dropped"]:
            m = mentions(index, rid, reqs[a["case_id"]].audit_at)
            reasons[why] += 1
            for k, v in m.items():
                if v[1] > 0:
                    kinds[k] += 1
    print("reasons:", dict(reasons))
    print("kinds of admissible evidence that mention these resources (count of resources):", dict(kinds))
    prefix_tally = Counter(rid.rsplit("_", 1)[0] for a in audit for rid, _ in a["dropped"])
    print("by resource type:", dict(prefix_tally))
    n_unplanned = sum(len(a["unplanned"]) for a in audit)
    print("unplanned (no allowed operation):", n_unplanned)

    print("\n=== 3. Cases 45, 61, 63")
    for cid in ("case_45", "case_61", "case_63"):
        a = next(x for x in audit if x["case_id"] == cid)
        print(cid, a["status"], "entries:", [(e["resource_id"], e["state"], e["evidence_id"]) for e in a["entries"]],
              "dropped:", a["dropped"])

    print("\n=== 4. Evidence file kinds (all 94 files)")
    print(dict(Counter(KIND_GROUP.get(r.kind, r.kind) for r in index.records)))
    pdfpng = sorted({r.file_id for r in index.records if r.kind in ("document", "document_line")}, key=case_sort_key)
    print("PDF/PNG files:", len(pdfpng))


if __name__ == "__main__":
    main()
