"""LLM backends under test, behind one streaming interface.

Client-side timings (`metrics.py`) are measured identically for every
backend and are the apples-to-apples numbers. `ServerStats` is whatever
the server reports on top (Ollama: prompt/eval durations; llama-server:
`timings`; OpenAI-style servers: token counts in `usage`) — useful for
splitting prefill from decode, but not comparable across engines field
by field.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import AsyncIterator, Protocol

import httpx
import ollama


@dataclass
class GenParams:
    """Identical for every backend: greedy decoding, so differences come
    from the engine, not sampling."""

    max_tokens: int = 160
    temperature: float = 0.0
    seed: int = 42
    num_ctx: int = 8192  # Ollama only; MLX/llama-server set context at launch


@dataclass
class ServerStats:
    prompt_tokens: int | None = None  # Ollama: only the tokens actually evaluated (cache misses)
    prompt_eval_s: float | None = None
    completion_tokens: int | None = None
    eval_s: float | None = None
    load_s: float | None = None


@dataclass
class Delta:
    text: str


@dataclass
class Done:
    stats: ServerStats


class Backend(Protocol):
    kind: str
    model: str

    def stream_chat(self, messages: list[dict], params: GenParams) -> AsyncIterator[Delta | Done]: ...

    async def aclose(self) -> None: ...


class OllamaBackend:
    """Native `/api/chat` — same client and call shape as the server's
    `ConversationEngine`, so this is the production path."""

    kind = "ollama"

    def __init__(self, model: str, base_url: str = "http://127.0.0.1:11434", client: ollama.AsyncClient | None = None):
        self.model = model
        self._client = client or ollama.AsyncClient(host=base_url)

    async def stream_chat(self, messages: list[dict], params: GenParams) -> AsyncIterator[Delta | Done]:
        stream = await self._client.chat(
            model=self.model,
            messages=messages,
            stream=True,
            think=False,
            options={
                "temperature": params.temperature,
                "seed": params.seed,
                "num_predict": params.max_tokens,
                "num_ctx": params.num_ctx,
            },
        )
        async for chunk in stream:
            piece = chunk["message"]["content"]
            if piece:
                yield Delta(piece)
            if chunk.get("done"):
                yield Done(
                    ServerStats(
                        prompt_tokens=chunk.get("prompt_eval_count"),
                        prompt_eval_s=_ns_to_s(chunk.get("prompt_eval_duration")),
                        completion_tokens=chunk.get("eval_count"),
                        eval_s=_ns_to_s(chunk.get("eval_duration")),
                        load_s=_ns_to_s(chunk.get("load_duration")),
                    )
                )

    async def prewarm(self, messages: list[dict], params: GenParams) -> None:
        """Evaluate `messages` (history + the reply just generated) with
        `num_predict 1`, so the next turn's prompt is a cached prefix.
        Ollama/gemma2 checkpoints the cache only at the end of a prompt,
        not after generated tokens — without this it re-reads its own
        last reply on every turn (ADR-0013 revision)."""
        await self._client.chat(
            model=self.model,
            messages=messages,
            stream=False,
            think=False,
            options={"temperature": params.temperature, "seed": params.seed, "num_predict": 1,
                     "num_ctx": params.num_ctx},
        )

    async def aclose(self) -> None:
        pass


class OpenAICompatBackend:
    """`/v1/chat/completions` with SSE streaming — `mlx_lm.server`,
    llama-server, LM Studio, or Ollama's own OpenAI endpoint."""

    kind = "openai"

    def __init__(self, model: str, base_url: str = "http://127.0.0.1:8080",
                 transport: httpx.AsyncBaseTransport | None = None, fold_system: bool = False):
        self.model = model
        self.fold_system = fold_system
        self._client = httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(300.0), transport=transport)

    async def stream_chat(self, messages: list[dict], params: GenParams) -> AsyncIterator[Delta | Done]:
        body = {
            "model": self.model,
            "messages": fold_system_prompt(messages) if self.fold_system else messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "temperature": params.temperature,
            "seed": params.seed,
            "max_tokens": params.max_tokens,
        }
        stats = ServerStats()
        async with self._client.stream("POST", "/v1/chat/completions", json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if payload == "[DONE]":
                    break
                event = json.loads(payload)
                for choice in event.get("choices") or []:
                    piece = (choice.get("delta") or {}).get("content")
                    if piece:
                        yield Delta(piece)
                _merge_stats(stats, event)
        yield Done(stats)

    async def aclose(self) -> None:
        await self._client.aclose()


def fold_system_prompt(messages: list[dict]) -> list[dict]:
    """Merge a leading system message into the first user message, the
    way Ollama's gemma2 template does (`{{ .System }} {{ .Prompt }}`) —
    for chat templates that reject the system role (Gemma 2 on HF/MLX)."""
    if not messages or messages[0]["role"] != "system":
        return messages
    system, rest = messages[0]["content"], [dict(m) for m in messages[1:]]
    if rest and rest[0]["role"] == "user":
        rest[0]["content"] = f"{system} {rest[0]['content']}"
    else:
        rest.insert(0, {"role": "user", "content": system})
    return rest


def _merge_stats(stats: ServerStats, event: dict) -> None:
    usage = event.get("usage")
    if usage:
        stats.prompt_tokens = usage.get("prompt_tokens", stats.prompt_tokens)
        stats.completion_tokens = usage.get("completion_tokens", stats.completion_tokens)
    timings = event.get("timings")  # llama-server
    if timings:
        stats.prompt_tokens = timings.get("prompt_n", stats.prompt_tokens)
        stats.prompt_eval_s = _ms_to_s(timings.get("prompt_ms"))
        stats.completion_tokens = timings.get("predicted_n", stats.completion_tokens)
        stats.eval_s = _ms_to_s(timings.get("predicted_ms"))


def _ns_to_s(value: int | None) -> float | None:
    return None if value is None else value / 1e9


def _ms_to_s(value: float | None) -> float | None:
    return None if value is None else value / 1e3


def make_backend(kind: str, model: str, base_url: str | None, fold_system: bool = False) -> Backend:
    if kind == "ollama":
        return OllamaBackend(model, base_url or "http://127.0.0.1:11434")
    if kind == "openai":
        return OpenAICompatBackend(model, base_url or "http://127.0.0.1:8080", fold_system=fold_system)
    raise ValueError(f"unknown backend kind {kind!r} (expected 'ollama' or 'openai')")
