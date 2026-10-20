"""Minimal client for the Claude Messages API (used for ad-text and account analysis)."""

import json
import re
from typing import Any

import httpx

from app.core.config import get_settings

DEFAULT_MODEL = "claude-sonnet-5-5"


class ClaudeError(Exception):
    pass


class ClaudeClient:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, *, http: httpx.AsyncClient | None = None) -> None:
        self.api_key = api_key
        self.model = model or DEFAULT_MODEL
        self._http = http

    async def complete(self, system: str, user: str, *, max_tokens: int = 3000) -> str:
        if not self.api_key:
            raise ClaudeError("کلید Claude API در تنظیمات وارد نشده است.")
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        url = get_settings().anthropic_api_base.rstrip("/") + "/v1/messages"
        try:
            if self._http is not None:
                resp = await self._http.post(url, json=body, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=180) as http:
                    resp = await http.post(url, json=body, headers=headers)
        except httpx.HTTPError as e:
            raise ClaudeError(f"اتصال به Claude برقرار نشد ({e.__class__.__name__}).") from e
        if resp.status_code != 200:
            try:
                msg = resp.json().get("error", {}).get("message", "")
            except ValueError:
                msg = resp.text[:200]
            if resp.status_code == 401:
                raise ClaudeError("کلید Claude API نامعتبر است.")
            if resp.status_code == 403:
                raise ClaudeError(f"Claude API دسترسی نداد: {msg}")
            raise ClaudeError(f"Claude API: HTTP {resp.status_code} {msg}")
        data = resp.json()
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")

    async def complete_json(self, system: str, user: str, *, max_tokens: int = 3000) -> dict[str, Any]:
        text = await self.complete(system, user, max_tokens=max_tokens)
        return parse_json_block(text)


def parse_json_block(text: str) -> dict[str, Any]:
    """Claude is asked for JSON only; tolerate a ```json fence or prose around it."""
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{") : text.rfind("}") + 1]
    try:
        out = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        raise ClaudeError("پاسخ Claude قابل خواندن نبود؛ دوباره امتحان کنید.") from e
    if not isinstance(out, dict):
        raise ClaudeError("پاسخ Claude قالب درستی نداشت.")
    return out
