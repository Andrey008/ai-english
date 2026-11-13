"""Client for claude_gateway's one-shot endpoint (`POST /v1/complete`).

Off the live voice path only (ADR-0016 §1): RU→EN question translation and
the interview review. Every call runs with no tools, no Claude Code
settings and our own system prompt, so the result depends only on the
prompt we send.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger("ai_english.claude_gateway")


class GatewayError(RuntimeError):
    """`kind`: not_configured | unauthorized | rate_limited | timeout |
    unreachable | failed. The message is fit to show the user."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class GatewayResult:
    text: str
    cost_usd: float | None
    session_id: str


class ClaudeGateway:
    def __init__(self, config: dict[str, Any], transport: httpx.AsyncBaseTransport | None = None):
        gw = config.get("claude_gateway") or {}
        self._base_url = str(gw.get("base_url") or "http://127.0.0.1:8091").rstrip("/")
        self._api_key = str(gw.get("api_key") or "")
        self._timeout_s = float(gw.get("timeout_s") or 600)
        self.translate_model = str(gw.get("translate_model") or "haiku")
        self.review_model = str(gw.get("review_model") or "sonnet")
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url, timeout=timeout, transport=self._transport,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )

    async def _paused_until(self) -> str | None:
        try:
            async with self._client(5) as client:
                return (await client.get("/health")).json().get("paused_until")
        except (httpx.HTTPError, ValueError):
            return None

    async def complete(self, prompt: str, *, system_prompt: str, model: str,
                       effort: str = "low", timeout_s: float | None = None) -> GatewayResult:
        if not self.configured:
            raise GatewayError("not_configured", "claude_gateway key is not set "
                               "(AI_ENGLISH__CLAUDE_GATEWAY__API_KEY in server/.env)")
        timeout_s = timeout_s or self._timeout_s
        body = {
            "prompt": prompt, "system_prompt": system_prompt, "model": model, "effort": effort,
            "tools": [], "setting_sources": [], "max_turns": 1, "timeout_s": timeout_s,
            "metadata": {"client": "ai-english"},
        }
        try:
            async with self._client(timeout_s + 30) as client:
                response = await client.post("/v1/complete", json=body)
        except httpx.TimeoutException as exc:
            raise GatewayError("timeout", f"claude_gateway did not answer in {timeout_s:.0f}s") from exc
        except httpx.HTTPError as exc:
            raise GatewayError("unreachable", f"claude_gateway is not reachable at {self._base_url}") from exc
        if response.status_code == 401:
            raise GatewayError("unauthorized", "claude_gateway rejected the key (check GATEWAY_CLIENTS)")
        if response.status_code == 504:
            paused = await self._paused_until()
            if paused:
                raise GatewayError("rate_limited", f"Claude usage limit reached; paused until {paused}")
            raise GatewayError("timeout", f"claude_gateway did not finish in {timeout_s:.0f}s")
        if response.status_code >= 400:
            raise GatewayError("failed", f"claude_gateway answered {response.status_code}: {response.text[:200]}")
        data = response.json()
        if data.get("is_error"):
            raise GatewayError("failed", f"Claude returned an error: {str(data.get('text'))[:200]}")
        logger.info("claude_gateway_complete", extra={"model": model, "cost_usd": data.get("cost_usd"),
                                                       "chars": len(data.get("text") or "")})
        return GatewayResult(text=data.get("text") or "", cost_usd=data.get("cost_usd"),
                             session_id=data.get("session_id") or "")
