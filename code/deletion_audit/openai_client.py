"""OpenAI client (Chat Completions API). Key: OPENAI_API_KEY. Caching, ledger and retries live in llm_common."""
from __future__ import annotations

import base64
import json
import os

from .llm_common import ModelClient, ModelUnavailable

API_URL = "https://api.openai.com/v1/chat/completions"
# A dated snapshot, so runs are reproducible. It reads images and accepts temperature 0, which the newer
# reasoning models do not.
DEFAULT_MODEL = "gpt-4.1-2025-04-14"


class OpenAIClient(ModelClient):
    provider = "openai"

    def __init__(self, model: str | None = None, **kwargs) -> None:
        super().__init__(model or os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL, **kwargs)

    def _fatal(self, code: int, body: str) -> str | None:
        if code == 401:
            return "OpenAI rejected the API key"
        if code == 429 and "insufficient_quota" in body:
            return "OpenAI account has no remaining quota or credit (insufficient_quota)"
        return None

    def _live(self, prompt, system, images, json_mode, max_tokens):
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key:
            raise ModelUnavailable("OPENAI_API_KEY is not set")
        content: list[dict] = [{"type": "text", "text": prompt}]
        for mime, data in images:
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"}})
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": content}]
        body = {"model": self.model, "messages": messages, "temperature": 0, "seed": 0, "max_tokens": max_tokens}
        if json_mode:
            body["response_format"] = {"type": "json_object"}     # the prompt must also mention JSON

        response = self._send(API_URL, body, {"Authorization": f"Bearer {key}"})
        choices = response.get("choices") or []
        if not choices:
            raise ModelUnavailable("no answer: no choices returned")
        choice = choices[0]
        text = (choice.get("message") or {}).get("content") or ""
        if not text and choice.get("finish_reason") == "content_filter":
            raise ModelUnavailable("no answer: blocked by content filter")
        usage = response.get("usage") or {}
        return text, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
