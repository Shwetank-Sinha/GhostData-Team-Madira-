"""Shared machinery for the model clients: reply type, usage ledger, content-addressed cache, retries.

A provider client only has to say how to build its request and read its answer. Everything else is here, so
Gemini and OpenAI behave the same: temperature 0, a cache keyed on everything that shaped the reply, and a
ledger entry for every call (cached or live) from which the usage report is built.

API keys come from environment variables, are sent only in a request header, and are never written anywhere.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .common import REPO_ROOT

CACHE_DIR = REPO_ROOT / "llm_cache"
RETRYABLE_HTTP = {429, 500, 502, 503, 504}
MAX_USEFUL_WAIT_S = 90.0     # a rate-limit wait longer than this is a quota problem, not a hiccup


class ModelUnavailable(Exception):
    """The provider cannot answer this call (no key, rejected key, quota, network, blocked reply)."""


@dataclass(frozen=True, slots=True)
class Reply:
    text: str
    input_tokens: int
    output_tokens: int          # visible answer plus any thinking tokens, which are billed as output
    latency_s: float
    cached: bool
    model: str
    provider: str = ""


class UsageLedger:
    """Thread-safe record of every call, summarised per model."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: list[dict] = []

    def record(self, purpose: str, reply: Reply) -> None:
        with self._lock:
            self._rows.append({"purpose": purpose, "provider": reply.provider, "model": reply.model,
                               "cached": reply.cached, "in": reply.input_tokens, "out": reply.output_tokens,
                               "latency": reply.latency_s})

    def rows(self) -> list[dict]:
        with self._lock:
            return list(self._rows)

    def summary(self) -> dict[str, dict]:
        """model -> provider, calls, live/cached split and token totals."""
        totals: dict[str, dict] = defaultdict(lambda: {"provider": "", "calls": 0, "live_calls": 0,
                                                       "cached_calls": 0, "input_tokens": 0, "output_tokens": 0})
        for row in self.rows():
            entry = totals[row["model"]]
            entry["provider"] = row["provider"]
            entry["calls"] += 1
            entry["cached_calls" if row["cached"] else "live_calls"] += 1
            entry["input_tokens"] += row["in"]
            entry["output_tokens"] += row["out"]
        return dict(totals)


def first_json_object(text: str) -> dict | None:
    """The first complete JSON object in a model reply, or None. Tolerates code fences and extra prose."""
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            value, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
            continue
        return value if isinstance(value, dict) else None
    return None


def retry_delay_seconds(error_body: str) -> float | None:
    """A wait the provider asks for inside a quota error body, if it states one in seconds."""
    try:
        parsed = json.loads(error_body)
    except json.JSONDecodeError:
        return None
    for item in (parsed.get("error", {}).get("details", []) if isinstance(parsed, dict) else []):
        delay = item.get("retryDelay") if isinstance(item, dict) else None
        if isinstance(delay, str) and delay.endswith("s"):
            try:
                return float(delay[:-1])
            except ValueError:
                return None
    return None


class ModelClient:
    """Base class: caching, ledger and retrying. Subclasses implement `_live`."""

    provider = ""

    def __init__(self, model: str, cache_dir: Path | None = CACHE_DIR, ledger: UsageLedger | None = None,
                 max_retries: int = 4, min_interval_s: float = 0.0) -> None:
        self.model = model
        self.cache_dir = cache_dir
        self.ledger = ledger or UsageLedger()
        self.max_retries = max_retries
        self.min_interval_s = min_interval_s        # spacing between live calls, for rate-limited keys
        self._lock = threading.Lock()
        self._last_call = 0.0

    # ---- provider hooks
    def _live(self, prompt: str, system: str, images: list[tuple[str, bytes]], json_mode: bool,
              max_tokens: int) -> tuple[str, int, int]:
        """One real call. Returns (text, input tokens, output tokens)."""
        raise NotImplementedError

    def _fatal(self, code: int, body: str) -> str | None:
        """A message when this HTTP error can never succeed on retry (daily quota, bad key); else None."""
        return None

    # ---- transport
    def _post(self, url: str, body: dict, headers: dict) -> dict:
        """One HTTPS call. A separate method so tests can replace it."""
        request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                         headers={"Content-Type": "application/json", **headers})
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))

    def _send(self, url: str, body: dict, headers: dict) -> dict:
        """_post with spacing, retries on transient errors, and fast failure on errors that cannot clear."""
        for attempt in range(self.max_retries + 1):
            with self._lock:
                wait = self._last_call + self.min_interval_s - time.time()
                if wait > 0:
                    time.sleep(wait)
                self._last_call = time.time()
            try:
                return self._post(url, body, headers)
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode("utf-8", "replace")
                fatal = self._fatal(exc.code, raw)
                if fatal:
                    raise ModelUnavailable(fatal) from exc
                hint = retry_delay_seconds(raw) if exc.code == 429 else None
                if hint is not None and hint > MAX_USEFUL_WAIT_S:
                    raise ModelUnavailable(f"quota exhausted for {self.model}; resets in about {hint / 3600:.1f} h") from exc
                if exc.code in RETRYABLE_HTTP and attempt < self.max_retries:
                    time.sleep(min(30.0, 2.0 * (2 ** attempt)))
                    continue
                raise ModelUnavailable(f"HTTP {exc.code}: {raw[:200]}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt < self.max_retries:
                    time.sleep(min(30.0, 2.0 * (2 ** attempt)))
                    continue
                raise ModelUnavailable(f"network error: {exc}") from exc
        raise ModelUnavailable("retries exhausted")

    # ---- cache
    def _cache_key(self, prompt: str, system: str, images: list[tuple[str, bytes]], json_mode: bool,
                   max_tokens: int) -> str:
        material = {"provider": self.provider, "model": self.model, "system": system, "prompt": prompt,
                    "json": json_mode, "max_tokens": max_tokens, "temperature": 0,
                    "images": [[mime, hashlib.sha256(data).hexdigest()] for mime, data in images]}
        return hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    # ---- public
    def generate(self, prompt: str, system: str = "", images: list[tuple[str, bytes]] | None = None,
                 json_mode: bool = False, max_tokens: int = 800, purpose: str = "") -> Reply:
        """One model turn. `images` is a list of (mime type, bytes). Repeating a call is served from the cache."""
        images = images or []
        key = self._cache_key(prompt, system, images, json_mode, max_tokens)
        path = self.cache_dir / f"{key}.json" if self.cache_dir else None
        if path is not None and path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            reply = Reply(data["text"], data["input_tokens"], data["output_tokens"], data.get("latency_s", 0.0),
                          True, self.model, self.provider)
            self.ledger.record(purpose, reply)
            return reply

        started = time.time()
        text, tokens_in, tokens_out = self._live(prompt, system, images, json_mode, max_tokens)
        reply = Reply(text, tokens_in, tokens_out, round(time.time() - started, 3), False, self.model, self.provider)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"text": reply.text, "input_tokens": reply.input_tokens,
                                        "output_tokens": reply.output_tokens, "latency_s": reply.latency_s,
                                        "model": self.model, "provider": self.provider}, ensure_ascii=False),
                            encoding="utf-8")
        self.ledger.record(purpose, reply)
        return reply
