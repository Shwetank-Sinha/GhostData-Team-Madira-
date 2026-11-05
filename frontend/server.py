"""A small local web server for the deletion-audit engine. Standard library only; it listens on this computer only.

    python code/main.py serve            open http://127.0.0.1:8000 in the browser

Safety: it answers only to localhost, refuses requests that did not come from its own page (a header check),
limits upload size, and only ever serves files from a fixed list.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .batches import MAX_BYTES, TEMPLATE, parse_batch
from .jobs import BUILTIN_ID, SUBMISSION_DIR, WEB_DIR, AppState, build_zip

STATIC = Path(__file__).parent / "static"
ID_RE = re.compile(r"^(?:[a-f0-9]{10}|builtin)$")
CASE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,60}$")
DOWNLOADS = {"output.csv": "text/csv; charset=utf-8", "evaluation_report.md": "text/markdown; charset=utf-8",
             "usage_report.md": "text/markdown; charset=utf-8", "skipped_requests.csv": "text/csv; charset=utf-8"}
SUBMISSION = {"code.zip": "application/zip", "chat_transcript.txt": "text/plain; charset=utf-8"}
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".json": "application/json"}
LOCAL_HOSTS = {"127.0.0.1", "localhost"}


def ensure_tools_on_path() -> None:
    """The two helper programs (for pictures and PDFs) are often installed but not on PATH on Windows."""
    if not shutil.which("tesseract"):
        for folder in (r"C:\Program Files\Tesseract-OCR", r"C:\Program Files (x86)\Tesseract-OCR"):
            if Path(folder).is_dir():
                os.environ["PATH"] += os.pathsep + folder
                break
    if not shutil.which("pdftotext"):
        packages = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
        if packages.is_dir():
            found = next(packages.rglob("pdftotext.exe"), None)
            if found:
                os.environ["PATH"] += os.pathsep + str(found.parent)


class Handler(BaseHTTPRequestHandler):
    state: AppState
    server_version = "GhostAudit"

    def log_message(self, fmt, *args):                          # keep the terminal quiet
        pass

    # ------------------------------------------------------------------ small helpers
    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload, status: int = 200) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._json({"error": message}, status)

    def _host_ok(self) -> bool:
        return self.headers.get("Host", "").split(":")[0] in LOCAL_HOSTS

    def _from_our_page(self) -> bool:
        return self.headers.get("X-Requested-With") == "ghost-audit-ui"

    def _body(self, limit: int = MAX_BYTES) -> bytes | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length < 0:
            return None
        if length > limit:
            # Read and throw away what was sent (up to a cap), so the browser can receive the polite refusal
            # instead of a dropped connection.
            remaining = min(length, 60_000_000)
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
            self.close_connection = True
            return None
        return self.rfile.read(length)

    def _download(self, path: Path, content_type: str, filename: str) -> None:
        if not path.is_file():
            return self._error(404, "That file is not available.")
        self._send(200, path.read_bytes(), content_type,
                   {"Content-Disposition": f'attachment; filename="{filename}"'})

    # ------------------------------------------------------------------ GET
    def do_GET(self) -> None:
        if not self._host_ok():
            return self._error(403, "Only reachable from this computer.")
        path = unquote(urlparse(self.path).path)
        if path == "/" or path == "/index.html":
            return self._static("index.html")
        if path.startswith("/static/"):
            return self._static(path[len("/static/"):])
        if path.startswith("/api/"):
            return self._api_get(path[len("/api/"):])
        self._error(404, "Not found.")

    def _static(self, name: str) -> None:
        target = (STATIC / name).resolve()
        if STATIC.resolve() not in target.parents or not target.is_file() or target.suffix not in STATIC_TYPES:
            return self._error(404, "Not found.")
        self._send(200, target.read_bytes(), STATIC_TYPES[target.suffix])

    def _api_get(self, route: str) -> None:
        state = self.state
        parts = route.split("/")
        if route == "status":
            with state.lock:
                running = state.running_job()
                dataset = state.dataset
                payload = {
                    "ready": state.ready, "error": state.error,
                    "dataset": {"requests": len(dataset.requests) if dataset else 0,
                                "practice_cases": len(dataset.sample_requests) if dataset else 0,
                                "evidence_files": len(dataset.evidence_files) if dataset else 0,
                                "readings": state.readings_count},
                    "tools": {"tesseract": bool(shutil.which("tesseract")), "pdftotext": bool(shutil.which("pdftotext"))},
                    "running_job": running.id if running else None,
                    "submission_files": [n for n in SUBMISSION if (SUBMISSION_DIR / n).is_file()],
                }
            return self._json(payload)
        if route == "template.csv":
            return self._send(200, TEMPLATE.encode("utf-8"), "text/csv; charset=utf-8",
                              {"Content-Disposition": 'attachment; filename="deletion_requests_template.csv"'})
        if route == "batches":
            with state.lock:
                items = sorted(state.batches.values(), key=lambda b: (b.id != BUILTIN_ID, b.created), reverse=False)
                return self._json({"batches": [b.public() for b in items]})
        if route == "jobs":
            with state.lock:
                jobs = sorted(state.jobs.values(), key=lambda j: j.created, reverse=True)[:12]
                return self._json({"jobs": [j.public(full=False) for j in jobs]})
        if len(parts) == 2 and parts[0] == "jobs" and ID_RE.match(parts[1]):
            job = state.jobs.get(parts[1])
            return self._json(job.public()) if job else self._error(404, "No such run.")
        if len(parts) == 4 and parts[0] == "jobs" and parts[2] == "cases" and ID_RE.match(parts[1]) and CASE_RE.match(parts[3]):
            detail = state.job_case(parts[1], parts[3])
            return self._json(detail) if detail else self._error(404, "No such case in this run.")
        if len(parts) == 4 and parts[0] == "jobs" and parts[2] == "download" and ID_RE.match(parts[1]):
            job = state.jobs.get(parts[1])
            if job is None:
                return self._error(404, "No such run.")
            name = parts[3]
            if name == "all_outputs.zip":
                names = [n for n in DOWNLOADS if (WEB_DIR / job.id / n).is_file()]
                return self._send(200, build_zip(job.id, names), "application/zip",
                                  {"Content-Disposition": 'attachment; filename="ghost_audit_results.zip"'})
            if name in DOWNLOADS:
                return self._download(WEB_DIR / job.id / name, DOWNLOADS[name], name)
            return self._error(404, "That file is not available.")
        if len(parts) == 2 and parts[0] == "submission" and parts[1] in SUBMISSION:
            return self._download(SUBMISSION_DIR / parts[1], SUBMISSION[parts[1]], parts[1])
        self._error(404, "Not found.")

    # ------------------------------------------------------------------ POST / DELETE
    def do_POST(self) -> None:
        if not self._host_ok() or not self._from_our_page():
            return self._error(403, "Not allowed.")
        path = unquote(urlparse(self.path).path)
        if path == "/api/batches":
            return self._upload()
        if path == "/api/jobs":
            return self._start_job()
        self._error(404, "Not found.")

    def do_DELETE(self) -> None:
        if not self._host_ok() or not self._from_our_page():
            return self._error(403, "Not allowed.")
        parts = unquote(urlparse(self.path).path).strip("/").split("/")
        if len(parts) == 3 and parts[:2] == ["api", "batches"] and ID_RE.match(parts[2]) and parts[2] != BUILTIN_ID:
            with self.state.lock:
                existed = self.state.batches.pop(parts[2], None)
            return self._json({"removed": bool(existed)})
        self._error(404, "Not found.")

    def _upload(self) -> None:
        raw = self._body()
        if raw is None:
            return self._error(413, f"The file is larger than {MAX_BYTES // 1_000_000} MB.")
        name = re.sub(r"[^\w .()-]", "", unquote(self.headers.get("X-Filename", "uploaded.csv")))[:80] or "uploaded.csv"
        parsed = parse_batch(raw)
        if parsed["fatal"]:
            return self._error(400, parsed["fatal"])
        if not parsed["requests"]:
            return self._json({"error": "None of the rows could be read. Fix the problems below and upload again.",
                               "problems": parsed["problems"][:50]}, 400)
        batch = self.state.add_batch(name, parsed)
        self._json({"batch": batch.public(), "preview": parsed["preview"], "problems": parsed["problems"][:50],
                    "problem_count": len(parsed["problems"])}, 201)

    def _start_job(self) -> None:
        raw = self._body(10_000)
        try:
            data = json.loads(raw or b"{}")
            batch_id, use_readings = str(data.get("batch_id", BUILTIN_ID)), bool(data.get("use_readings", True))
        except (json.JSONDecodeError, AttributeError):
            return self._error(400, "That request was not understood.")
        if not ID_RE.match(batch_id):
            return self._error(400, "Unknown batch.")
        if self.state.running_job() is not None:
            return self._error(409, "A run is already in progress. Wait for it to finish.")
        try:
            job = self.state.start_job(batch_id, use_readings)
        except KeyError as exc:
            return self._error(404, str(exc.args[0]))
        self._json({"job": job.public()}, 202)


def serve(port: int = 8000, open_browser: bool = True) -> int:
    ensure_tools_on_path()
    state = AppState()
    Handler.state = state
    threading.Thread(target=state.warm_up, daemon=True).start()
    httpd = None
    for candidate in range(port, port + 10):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", candidate), Handler)
            port = candidate
            break
        except OSError:
            continue
    if httpd is None:
        print(f"Could not open a port between {port} and {port + 9}. Close the other program and try again.")
        return 1
    url = f"http://127.0.0.1:{port}"
    print(f"Ghost Data Audit is running at {url}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.8, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
    return 0
