"""Per-turn timing, measured client-side the same way for every backend.

`first_sentence_s` is the number that matters for the voice pipeline:
TTS starts on the first complete sentence (`ConversationEngine`'s
`SENTENCE_END`), so first audio ≈ STT + this + Piper's first chunk
(~0.1s, CPU, backend-independent). TTFT mostly reflects prefill.
"""
from __future__ import annotations

import statistics
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from app.conversation_engine import SENTENCE_END
from bench.backends import Backend, Delta, Done, GenParams


@dataclass
class TurnResult:
    turn: int
    cold: bool  # first turn of a fresh (cache-busted) conversation
    ttft_s: float | None
    first_sentence_s: float | None
    total_s: float
    chunks: int
    reply: str
    completion_tokens: int | None = None
    completion_tokens_source: str = "server"  # or "chunks" when the server reports none
    decode_tps: float | None = None
    server: dict[str, Any] = field(default_factory=dict)
    prefill_tps: float | None = None  # server-reported prompt tokens / prompt eval time
    peak_rss_mb: float | None = None
    prewarm_s: float | None = None  # --prewarm-reply: cache refresh after this reply (hidden behind TTS)
    error: str | None = None


async def measure_turn(
    backend: Backend, messages: list[dict], params: GenParams, turn: int, cold: bool
) -> TurnResult:
    started = time.perf_counter()
    ttft = first_sentence = None
    reply = ""
    chunks = 0
    stats = None
    async for event in backend.stream_chat(messages, params):
        now = time.perf_counter() - started
        if isinstance(event, Delta):
            chunks += 1
            reply += event.text
            if ttft is None:
                ttft = now
            if first_sentence is None and SENTENCE_END.search(reply + " "):
                first_sentence = now
        elif isinstance(event, Done):
            stats = event.stats
    total = time.perf_counter() - started
    if first_sentence is None and reply.strip():
        first_sentence = total  # one-sentence reply without trailing space

    result = TurnResult(
        turn=turn, cold=cold, ttft_s=ttft, first_sentence_s=first_sentence,
        total_s=total, chunks=chunks, reply=reply,
    )
    if stats is not None:
        result.server = {k: v for k, v in asdict(stats).items() if v is not None}
        result.completion_tokens = stats.completion_tokens
        if stats.prompt_tokens and stats.prompt_eval_s:
            result.prefill_tps = stats.prompt_tokens / stats.prompt_eval_s
    if result.completion_tokens is None:
        result.completion_tokens, result.completion_tokens_source = chunks, "chunks"
    if ttft is not None and result.completion_tokens and result.completion_tokens > 1 and total > ttft:
        result.decode_tps = (result.completion_tokens - 1) / (total - ttft)
    return result


def summarize(values: list[float | None]) -> dict[str, float] | None:
    clean = sorted(v for v in values if v is not None)
    if not clean:
        return None
    p90_index = min(len(clean) - 1, round(0.9 * (len(clean) - 1)))
    return {
        "n": len(clean),
        "median": statistics.median(clean),
        "p90": clean[p90_index],
        "min": clean[0],
        "max": clean[-1],
    }
