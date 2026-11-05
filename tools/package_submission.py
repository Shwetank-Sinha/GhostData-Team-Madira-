"""Build the submission folder: submission/code.zip and submission/output.csv.

    python tools/package_submission.py

Run `python code/main.py run` first, so output.csv and the two reports belong to the same run.

code.zip holds an explicit list of files only: README.md, code/, frontend/, tools/, custom_cases/, Start Website.bat, evaluation_test/run_evaluation.py and an
evaluation/ folder with evaluation_report.md and usage_report.md (the newest of each). It never holds the
dataset, caches, run output, archives or anything that looks like a secret; the script stops if it finds one.
"""
from __future__ import annotations

import csv
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from deletion_audit.common import case_sort_key  # noqa: E402

OUT_DIR = ROOT / "submission"
ARCHIVE_SUFFIXES = {".zip", ".tar", ".gz", ".tgz", ".7z", ".rar", ".bz2", ".xz"}
SECRET_PATTERNS = [re.compile(p) for p in (
    r"AQ\.Ab8[0-9A-Za-z_-]{20,}", r"sk-(?:proj-)?[A-Za-z0-9_-]{30,}", r"AIza[0-9A-Za-z_-]{30,}",
    r"AKIA[0-9A-Z]{16}", r"-----BEGIN [A-Z ]*PRIVATE KEY-----", r"(?i)aws_secret_access_key\s*=\s*\S+",
    r"(?i)bearer\s+[A-Za-z0-9._-]{30,}")]


def newest(pattern: str) -> Path:
    found = sorted((ROOT / "evaluation_test").glob(pattern), key=lambda p: p.stat().st_mtime)
    if not found:
        raise SystemExit(f"no file matches evaluation_test/{pattern}; run `python code/main.py run` first")
    return found[-1]


def check_output(path: Path) -> None:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    if rows[0] != ["case_id", "deletion_status", "steps_json"]:
        raise SystemExit(f"output.csv has the wrong header: {rows[0]}")
    ids = [r[0] for r in rows[1:]]
    with (ROOT / "dataset" / "deletion_requests.csv").open(newline="", encoding="utf-8") as handle:
        expected = [r["case_id"] for r in csv.DictReader(handle)]
    if len(ids) != 518 or sorted(ids, key=case_sort_key) != ids or set(ids) != set(expected) or len(set(ids)) != len(ids):
        raise SystemExit(f"output.csv is not exactly one row per request in sorted order ({len(ids)} rows)")


def collect() -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = [("README.md", ROOT / "README.md"),
                                     ("evaluation_test/run_evaluation.py", ROOT / "evaluation_test" / "run_evaluation.py")]
    for folder in ("code", "frontend", "tools", "custom_cases"):
        for path in sorted((ROOT / folder).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                files.append((path.relative_to(ROOT).as_posix(), path))
    files.append(("Start Website.bat", ROOT / "Start Website.bat"))
    files.append(("evaluation/evaluation_report.md", newest("evaluation_report_*.md")))
    files.append(("evaluation/usage_report.md", newest("usage_report_*.md")))
    return files


def main() -> int:
    output = ROOT / "output.csv"
    check_output(output)
    stale = [p.name for p in (newest("evaluation_report_*.md"), newest("usage_report_*.md"))
             if p.stat().st_mtime + 5 < output.stat().st_mtime]
    if stale:
        raise SystemExit(f"{stale} are older than output.csv; run `python code/main.py run` again")

    files = collect()
    for arcname, path in files:
        if Path(arcname).suffix.lower() in ARCHIVE_SUFFIXES:
            raise SystemExit(f"nested archive in the package: {arcname}")
        if arcname.startswith(("dataset/", "runs/", ".cache/", "llm_cache/")):
            raise SystemExit(f"not allowed in the package: {arcname}")
        if not path.is_file():
            raise SystemExit(f"missing file: {arcname}")
        text = path.read_bytes().decode("utf-8", "ignore")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                raise SystemExit(f"something that looks like a secret is in {arcname}; not packaging")

    OUT_DIR.mkdir(exist_ok=True)
    archive = OUT_DIR / "code.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, path in files:
            info = zipfile.ZipInfo(arcname, date_time=(2026, 1, 1, 0, 0, 0))   # fixed time: same input, same zip
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, path.read_bytes())
    shutil.copyfile(output, OUT_DIR / "output.csv")
    print(f"wrote {archive.relative_to(ROOT)} ({archive.stat().st_size} bytes, {len(files)} files) and submission/output.csv")
    for arcname, _ in files:
        if not arcname.startswith("code/deletion_audit/"):
            print("   ", arcname)
    print(f"    code/deletion_audit/ ({sum(a.startswith('code/deletion_audit/') for a, _ in files)} modules)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
