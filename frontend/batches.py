"""Reading and checking an uploaded batch of deletion requests (a CSV file).

A batch must have the same columns as dataset/deletion_requests.csv. Column order does not matter and extra
columns are ignored. Every row is checked, and every problem is explained in plain words, so a person can
fix the file and upload it again.
"""
from __future__ import annotations

import csv
import io

from deletion_audit.data import EXPECTED_COLUMNS, REPORTED_STATUSES, _make_request

COLUMNS = EXPECTED_COLUMNS["deletion_requests.csv"]
MAX_BYTES = 5_000_000
MAX_ROWS = 5000

TEMPLATE = (
    ",".join(COLUMNS) + "\n"
    'case_900,someone@example.com,2026-07-16T08:00:00Z,COMPLETE,2026-07-18T02:00:00Z,2026-07-19T13:00:00Z,'
    '"Please delete my account and all of my personal data."\n'
    'case_901,another.person@example.com,2026-08-02T09:30:00Z,NOT_STARTED,2026-08-03T12:00:00Z,2026-08-05T10:00:00Z,'
    '"I would like my account erased."\n'
)

_DATE_HINT = "a date and time like 2026-07-16T08:00:00Z"


def template_for(requests) -> str:
    """A working example file: real customers from the data under new case ids, so it can be run as it is."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    stamp = lambda moment: moment.strftime("%Y-%m-%dT%H:%M:%SZ")
    for number, r in enumerate(list(requests)[:4], start=1):
        writer.writerow([f"example_{number:03d}", r.email, stamp(r.requested_at), r.reported_status,
                         stamp(r.reported_at), stamp(r.audit_at), r.request_text])
    return out.getvalue()


def _friendly(column: str, error: Exception) -> str:
    """Turn a technical error into a sentence a person can act on."""
    text = str(error)
    if "reported_status" in text:
        return f"reported_status must be one of {', '.join(sorted(REPORTED_STATUSES))}"
    if column in ("requested_at", "reported_at", "audit_at"):
        return f"{column} is not {_DATE_HINT}"
    return text


def parse_batch(raw: bytes) -> dict:
    """Check an uploaded file. Returns the usable requests, the problems found and a short preview."""
    if len(raw) > MAX_BYTES:
        return {"fatal": f"The file is larger than {MAX_BYTES // 1_000_000} MB.", "requests": [], "problems": [],
                "total_rows": 0, "preview": []}
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return {"fatal": "The file is not plain text in UTF-8. Save it as CSV (UTF-8) and try again.",
                "requests": [], "problems": [], "total_rows": 0, "preview": []}

    reader = csv.DictReader(io.StringIO(text, newline=""))
    header = [h.strip() for h in (reader.fieldnames or [])]
    missing = [c for c in COLUMNS if c not in header]
    if missing:
        return {"fatal": "These columns are missing: " + ", ".join(missing) + ".", "requests": [], "problems": [],
                "total_rows": 0, "preview": []}

    requests, problems, preview = [], [], []
    seen: set[str] = set()
    total = 0
    for line_no, row in enumerate(reader, start=2):               # line 1 is the header
        total += 1
        if total > MAX_ROWS:
            return {"fatal": f"The file has more than {MAX_ROWS} rows. Split it into smaller batches.",
                    "requests": [], "problems": [], "total_rows": total, "preview": []}
        clean = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        case_id = clean.get("case_id", "")
        if not case_id:
            problems.append({"line": line_no, "case_id": "", "message": "case_id is empty"})
            continue
        if case_id in seen:
            problems.append({"line": line_no, "case_id": case_id, "message": "this case_id appears more than once"})
            continue
        seen.add(case_id)
        empty = [c for c in COLUMNS if not clean.get(c)]
        if empty:
            problems.append({"line": line_no, "case_id": case_id, "message": "empty: " + ", ".join(empty)})
            continue
        try:
            request = _make_request(clean)
        except (ValueError, KeyError) as exc:
            column = next((c for c in ("reported_status", "requested_at", "reported_at", "audit_at")
                           if c in str(exc) or not _parses(clean, c)), "")
            problems.append({"line": line_no, "case_id": case_id, "message": _friendly(column, exc)})
            continue
        requests.append(request)
        if len(preview) < 5:
            preview.append({"case_id": case_id, "email": request.email, "reported_status": request.reported_status,
                            "audit_at": clean["audit_at"], "request_text": request.request_text[:140]})
    if total == 0:
        return {"fatal": "The file has a header but no requests.", "requests": [], "problems": [], "total_rows": 0,
                "preview": []}
    return {"fatal": None, "requests": requests, "problems": problems, "total_rows": total, "preview": preview}


def _parses(clean: dict, column: str) -> bool:
    """True when a date column holds a readable date (used only to name the culprit in an error)."""
    if column == "reported_status":
        return clean.get(column) in REPORTED_STATUSES
    from deletion_audit.common import parse_ts
    try:
        parse_ts(clean[column])
        return True
    except (ValueError, KeyError):
        return False
