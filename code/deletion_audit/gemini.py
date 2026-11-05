"""Gemini client (Google AI Studio API). Key: GEMINI_API_KEY. Caching, ledger and retries live in llm_common."""
from __future__ import annotations

import base64
import json
import os

from .llm_common import ModelClient, ModelUnavailable

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-3.5-flash"          # pinned by name, not a "-latest" alias, so runs are reproducible


class GeminiClient(ModelClient):
    provider = "google"

    def __init__(self, model: str | None = None, **kwargs) -> None:
        super().__init__(model or os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL, **kwargs)

    def _fatal(self, code: int, body: str) -> str | None:
        if code in (400, 401, 403) and "API key" in body:
            return "Gemini rejected the API key"
        return None

    def _live(self, prompt, system, images, json_mode, max_tokens):
        key = os.environ.get("GEMINI_API_KEY", "")
        if not key:
            raise ModelUnavailable("GEMINI_API_KEY is not set")
        parts = [{"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode("ascii")}}
                 for mime, data in images]
        parts.append({"text": prompt})
        config = {"temperature": 0, "maxOutputTokens": max_tokens, "thinkingConfig": {"thinkingBudget": 0}}
        if json_mode:
            config["responseMimeType"] = "application/json"
        body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": config}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        response = self._send(f"{API_ROOT}/models/{self.model}:generateContent", body, {"x-goog-api-key": key})
        candidates = response.get("candidates") or []
        if not candidates:
            raise ModelUnavailable(f"no answer: {(response.get('promptFeedback') or {}).get('blockReason', 'no candidates')}")
        answer_parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in answer_parts if not p.get("thought"))
        usage = response.get("usageMetadata") or {}
        return (text, int(usage.get("promptTokenCount", 0)),
                int(usage.get("candidatesTokenCount", 0)) + int(usage.get("thoughtsTokenCount", 0)))
