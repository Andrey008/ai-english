"""Conversation engine: Ollama LLM integration (STORY-02-04).

Per-session dialogue history + sentence-boundary-chunked streaming
(TTS is chunked per sentence, not per token — ADR-0006). Cancellation
is a plain flag checked between chunks, not direct manipulation of the
in-flight stream from another task — see `cancel()`'s docstring for why.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from typing import Any, AsyncIterator

import ollama

from app.persona import DEFAULT_SYSTEM_PROMPT

logger = logging.getLogger("ai_english.conversation")

SENTENCE_END = re.compile(r"[.!?]+[\"')\]]?\s")

_SYSTEM_SLOT = "{{ if .System }}{{ .System }}"

# Sent as a user turn appended to the live history, so the request is a
# strict extension of what Ollama already has cached (see `_compact`).
_COMPACTION_REQUEST = (
    "[Note from the app, not from the user: pause the conversation for a "
    "moment. Write notes on this whole conversation so far, for your own "
    "reference later. Keep every concrete fact the user shared (names, "
    "places, people, pets, likes and dislikes, plans, opinions) and the "
    "topics you covered, in order; skip pleasantries. Third person, plain "
    "prose, at most 150 words. Output only the notes.]"
)
_SUMMARY_HEADER = (
    "CONVERSATION SO FAR (summary of the earlier part of this conversation; "
    "the most recent messages follow verbatim):"
)


class ConversationEngineError(RuntimeError):
    pass


class ConversationEngine:
    def __init__(self, config: dict[str, Any]):
        self._model = config["llm"]["model"]
        self._client = ollama.AsyncClient()
        self._histories: dict[str, list[dict]] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._prompt_head: str | None = None
        self._prewarm_tasks: set[asyncio.Task] = set()
        compaction = config["llm"].get("compaction", {})
        self._compact_trigger_tokens = int(compaction.get("trigger_tokens", 0))
        self._compact_keep_messages = int(compaction.get("keep_recent_messages", 6))
        self._base_prompts: dict[str, str] = {}
        self._compaction_tasks: dict[str, asyncio.Task] = {}
        self._pending_summaries: dict[str, tuple[str, int]] = {}
        self._reply_prewarm = bool(config["llm"].get("reply_prewarm", True))
        self._reply_prewarm_tasks: dict[str, asyncio.Task] = {}

    async def check_ready(self) -> None:
        """Fail fast at server startup if Ollama is unreachable or the
        configured model hasn't been pulled — matches STT/TTS's pattern
        of validating dependencies before serving, not mid-session.
        """
        try:
            resp = await self._client.list()
        except (ConnectionError, OSError) as exc:
            raise ConversationEngineError(f"Ollama unreachable: {exc}") from exc
        available = {m.model for m in resp.models}
        if self._model not in available:
            raise ConversationEngineError(
                f"Model {self._model!r} not found in Ollama (available: {sorted(available)})"
            )
        try:
            template = (await self._client.show(self._model)).template or ""
        except (ollama.ResponseError, ConnectionError, OSError):
            template = ""
        head, sep, _ = template.partition(_SYSTEM_SLOT)
        # Only simple "<literal>{{ .System }}..." templates (gemma2) are
        # understood; anything else just skips the prewarm optimization.
        self._prompt_head = head if sep and "{{" not in head else None

    def start_session(
        self,
        session_id: str,
        system_prompt: str | None = None,
        opening_message: str | None = None,
    ) -> None:
        """`opening_message` seeds history with an assistant turn the
        character already spoke (a scenario's proactive opening line,
        `STORY-03-04`) before any user turn — so the next real
        `generate_reply` call has that context, instead of the LLM being
        unaware the character already said something.
        """
        history = [{"role": "system", "content": system_prompt or DEFAULT_SYSTEM_PROMPT}]
        if opening_message:
            history.append({"role": "assistant", "content": opening_message})
        self._histories[session_id] = history
        self._base_prompts[session_id] = history[0]["content"]
        logger.info("conversation_session_started", extra={"session_id": session_id})
        if self._prompt_head is not None:
            task = asyncio.get_running_loop().create_task(
                self._prewarm(session_id, self._prompt_head + history[0]["content"])
            )
            self._prewarm_tasks.add(task)
            task.add_done_callback(self._prewarm_tasks.discard)

    async def _prewarm(self, session_id: str, prompt_prefix: str) -> None:
        """Process the session's system prompt into Ollama's KV cache while
        the user is still saying their first line. Measured on gemma2:27b
        (STORY-05-11): a cold ~520-token prompt costs ~7.5s before the
        first token, which made every session's first reply take 8-13s;
        later turns are fast because each request extends the previous
        one. Ollama only reuses cache for a sequence that is a strict
        token prefix of the next request (no partial rewind with
        gemma2's sliding-window attention), so this sends the *raw*
        rendered prompt head — exactly what the real first request starts
        with — rather than a chat call, whose closing tags wouldn't match.
        """
        started = time.monotonic()
        try:
            await self._client.generate(
                model=self._model, prompt=prompt_prefix, raw=True, options={"num_predict": 1}
            )
        except (ollama.ResponseError, ConnectionError, OSError) as exc:
            logger.warning("llm_prewarm_failed", extra={"session_id": session_id, "error": str(exc)})
            return
        logger.info(
            "llm_prewarm_done",
            extra={"session_id": session_id, "duration_s": round(time.monotonic() - started, 2)},
        )

    def last_reply(self, session_id: str) -> str | None:
        """The character's most recent line (STT context prompt)."""
        for message in reversed(self._histories.get(session_id, [])):
            if message["role"] == "assistant":
                return message["content"]
        return None

    def end_session(self, session_id: str) -> None:
        for tasks in (self._compaction_tasks, self._reply_prewarm_tasks):
            task = tasks.pop(session_id, None)
            if task is not None:
                task.cancel()
        self._histories.pop(session_id, None)
        self._cancel_events.pop(session_id, None)
        self._base_prompts.pop(session_id, None)
        self._pending_summaries.pop(session_id, None)
        logger.info("conversation_session_ended", extra={"session_id": session_id})

    async def generate_reply(self, session_id: str, user_text: str) -> AsyncIterator[dict]:
        """Yields {"type": "sentence", "text": ...} as sentences complete,
        then a final {"type": "done", "full_text": ...}. Raises
        ConversationEngineError on an unreachable/failing Ollama backend.
        """
        await self._cancel_reply_prewarm(session_id)
        await self._defer_compaction(session_id)
        history = self._histories.setdefault(
            session_id, [{"role": "system", "content": DEFAULT_SYSTEM_PROMPT}]
        )
        history.append({"role": "user", "content": user_text})

        cancel_event = asyncio.Event()
        self._cancel_events[session_id] = cancel_event

        try:
            stream = await self._client.chat(
                model=self._model, messages=history, stream=True, think=False
            )
        except (ollama.ResponseError, ConnectionError, OSError) as exc:
            history.pop()  # don't leave a dangling user turn with no reply
            raise ConversationEngineError(f"Ollama request failed: {exc}") from exc

        buf = ""
        full_reply = ""
        cancelled = False
        try:
            async for chunk in stream:
                if cancel_event.is_set():
                    cancelled = True
                    break
                piece = chunk["message"]["content"]
                buf += piece
                full_reply += piece
                match = SENTENCE_END.search(buf)
                while match:
                    sentence = buf[: match.end()].strip()
                    if sentence:
                        yield {"type": "sentence", "text": sentence}
                    buf = buf[match.end():]
                    match = SENTENCE_END.search(buf)
        except (ollama.ResponseError, ConnectionError, OSError) as exc:
            raise ConversationEngineError(f"Ollama stream failed: {exc}") from exc
        finally:
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                await aclose()
            self._cancel_events.pop(session_id, None)

        if cancelled:
            if full_reply:
                history.append({"role": "assistant", "content": full_reply})
            logger.info("conversation_generation_cancelled", extra={"session_id": session_id})
            yield {"type": "cancelled", "full_text": full_reply}
            return

        if buf.strip():
            yield {"type": "sentence", "text": buf.strip()}
        history.append({"role": "assistant", "content": full_reply})
        self._maybe_start_compaction(session_id)
        if session_id not in self._compaction_tasks:  # its summary request already extends this history
            self._start_reply_prewarm(session_id, history)
        yield {"type": "done", "full_text": full_reply}

    def _start_reply_prewarm(self, session_id: str, history: list[dict]) -> None:
        """Ollama with gemma2 checkpoints its cache only at the end of a
        prompt, not after the tokens it generated — so without this the
        next turn re-reads the whole previous reply before the first
        token (~0.25-0.5s, growing with reply length). Re-evaluating
        history + reply with `num_predict 1` while the reply is still
        being spoken makes the next request a cached prefix again.
        Measured (AE-2 bench, free mode): first sentence 1.20s -> 0.81s,
        on par with MLX, which caches generated tokens itself (ADR-0013).
        """
        if not self._reply_prewarm:
            return
        messages = list(history)  # snapshot: the next user turn appends to `history`
        task = asyncio.get_running_loop().create_task(self._run_reply_prewarm(session_id, messages))
        self._reply_prewarm_tasks[session_id] = task
        task.add_done_callback(
            lambda t: self._reply_prewarm_tasks.pop(session_id, None)
            if self._reply_prewarm_tasks.get(session_id) is t else None
        )

    async def _run_reply_prewarm(self, session_id: str, messages: list[dict]) -> None:
        started = time.monotonic()
        try:
            await self._client.chat(
                model=self._model, messages=messages, stream=False, think=False, options={"num_predict": 1}
            )
        except (ollama.ResponseError, ConnectionError, OSError) as exc:
            logger.warning("llm_reply_prewarm_failed", extra={"session_id": session_id, "error": str(exc)})
            return
        logger.info(
            "llm_reply_prewarm_done",
            extra={"session_id": session_id, "duration_s": round(time.monotonic() - started, 2)},
        )

    async def _cancel_reply_prewarm(self, session_id: str) -> None:
        """Normally long finished (it takes ~0.5-1s; the reply's playback
        takes several). If the user cuts in first, their turn wins —
        same rule as `_defer_compaction`."""
        task = self._reply_prewarm_tasks.pop(session_id, None)
        if task is None or task.done():
            return
        task.cancel()
        await asyncio.wait({task})
        logger.info("llm_reply_prewarm_cancelled", extra={"session_id": session_id})

    def _maybe_start_compaction(self, session_id: str) -> None:
        """In-session context compaction (STORY-05-11 follow-up). History
        is otherwise unbounded, and past the model's window (gemma2:27b:
        8K) Ollama's context shift drops the tokens right after the first
        four, i.e. the persona prompt goes first. Starts right after a
        reply is generated, so the work overlaps that reply's playback
        and the user's next utterance instead of the reply path.
        """
        if self._compact_trigger_tokens <= 0 or session_id in self._compaction_tasks:
            return
        history = self._histories.get(session_id)
        if history is None or _estimate_tokens(history) < self._compact_trigger_tokens:
            return
        task = asyncio.get_running_loop().create_task(self._compact(session_id, history))
        self._compaction_tasks[session_id] = task
        task.add_done_callback(lambda _: self._compaction_tasks.pop(session_id, None))

    async def _defer_compaction(self, session_id: str) -> None:
        """A user turn always wins over compaction: Ollama serves one
        request at a time here, so a summary/prewarm still in flight
        would queue the reply behind it. Cancelling closes the HTTP
        stream, which stops Ollama's work (see `cancel()`); a finished
        summary is kept in `_pending_summaries` and the next attempt only
        redoes the prewarm.
        """
        task = self._compaction_tasks.get(session_id)
        if task is None or task.done():
            return
        task.cancel()
        await asyncio.wait({task})
        logger.info(
            "llm_compaction_deferred",
            extra={
                "session_id": session_id,
                "summary_ready": session_id in self._pending_summaries,
            },
        )

    async def _compact(self, session_id: str, history: list[dict]) -> None:
        """Two phases, both background and cancellable:

        1. Summary — sent as the live history plus `_COMPACTION_REQUEST`,
           a strict extension of the cached prompt, so Ollama only
           evaluates the new tail (prompt eval is ~50-75 tok/s for
           gemma2:27b here, so re-reading the whole history would cost
           over a minute).
        2. Prewarm — the compacted history (persona + summary + recent
           messages) is evaluated once with `num_predict: 1`, and only
           then swapped in. Swapping before it's cached would make the
           next reply re-evaluate ~1-2K tokens (20s+) on the reply path.
           The prompt cache keeps the old history's state too, so a
           reply that cancels this phase loses nothing.
        """
        started = time.monotonic()
        tokens_before = _estimate_tokens(history)
        try:
            pending = self._pending_summaries.get(session_id)
            if pending is None:
                cut = self._compaction_cut(history)
                if cut is None:
                    return
                logger.info(
                    "llm_compaction_started",
                    extra={"session_id": session_id, "est_tokens": tokens_before, "messages": len(history)},
                )
                resp = await self._client.chat(
                    model=self._model,
                    messages=history + [{"role": "user", "content": _COMPACTION_REQUEST}],
                    stream=False,
                    think=False,
                    options={"num_predict": 300},
                )
                summary = resp["message"]["content"].strip()
                if not summary:
                    logger.warning("llm_compaction_failed", extra={"session_id": session_id, "error": "empty summary"})
                    return
                pending = (summary, cut)
                self._pending_summaries[session_id] = pending
                logger.info(
                    "llm_compaction_summary_done",
                    extra={
                        "session_id": session_id,
                        "duration_s": round(time.monotonic() - started, 2),
                        "summary_words": len(summary.split()),
                    },
                )

            summary, cut = pending
            base = self._base_prompts.get(session_id, history[0]["content"])
            compacted = [{"role": "system", "content": f"{base}\n\n{_SUMMARY_HEADER}\n{summary}"}]
            compacted += history[cut:]
            expected_len = len(history)
            prewarm_started = time.monotonic()
            await self._client.chat(
                model=self._model, messages=compacted, stream=False, think=False, options={"num_predict": 1}
            )
            if self._histories.get(session_id) is not history or len(history) != expected_len:
                return  # session ended or moved on meanwhile; retry after the next reply
            self._histories[session_id] = compacted
            self._pending_summaries.pop(session_id, None)
            logger.info(
                "llm_compaction_applied",
                extra={
                    "session_id": session_id,
                    "est_tokens_before": tokens_before,
                    "est_tokens_after": _estimate_tokens(compacted),
                    "messages_before": expected_len,
                    "messages_after": len(compacted),
                    "prewarm_s": round(time.monotonic() - prewarm_started, 2),
                },
            )
        except (ollama.ResponseError, ConnectionError, OSError) as exc:
            logger.warning("llm_compaction_failed", extra={"session_id": session_id, "error": str(exc)})

    def _compaction_cut(self, history: list[dict]) -> int | None:
        """Index of the first message kept verbatim: the last
        `keep_recent_messages`, moved back to start on a user message so
        the compacted history still alternates system -> user -> assistant.
        """
        cut = len(history) - self._compact_keep_messages
        while cut > 1 and history[cut]["role"] != "user":
            cut -= 1
        return cut if cut > 1 else None

    def cancel(self, session_id: str) -> bool:
        """Signal generation to stop for `session_id`.

        Sets a flag `generate_reply` checks between chunks, rather than
        reaching into the live stream directly — that stream is owned by
        whichever task is running `generate_reply`'s `async for` loop, and
        calling `aclose()` on an async generator while it's mid-iteration
        elsewhere raises. `generate_reply` closes its own stream in its
        `finally` block once it sees the flag, which empirically does
        stop Ollama's server-side generation (verified: an abandoned
        ~117s generation freed the model runner in <1s for a follow-up
        request — see ADR-0006/FINDINGS open item #4).
        """
        event = self._cancel_events.get(session_id)
        if event is None:
            return False
        event.set()
        return True


def _estimate_tokens(messages: list[dict]) -> int:
    """~4 characters per token for English, plus per-message overhead —
    good enough to decide *when* to compact; nothing depends on it being
    exact."""
    return sum(math.ceil(len(m["content"]) / 4) + 4 for m in messages)
