"""WebSocket streaming session endpoint (STORY-02-05).

Wires VAD -> STT -> conversation engine -> TTS end-to-end for a single
active session (no multi-tenancy, ADR-0001). See the module docstring
sections below for the wire protocol.

## Protocol (proto_version 1)

Binary frames carry raw 16-bit PCM mono 16kHz audio, both directions.
JSON text frames carry everything else, always with a `"type"` field.

Client -> Server:
- `{"type": "session_start", "proto_version": 1, "session_id": "<optional>", "character_id": "<optional>", "scenario_id": "<optional>", "english_level": "<optional>", "use_memory": <optional bool>}`
  First message on the connection. Omit `session_id` for a new session;
  pass a previous one to attempt reconnect (honored only within the
  registry's grace window — see `session_registry.py`). `character_id`
  selects a preset from `presets.py` (`STORY-02-07`) — its
  `role_description`/`tts_voice_id` drive the session (system prompt is
  composed via `persona.render_system_prompt`, `ADR-0008`); omitted or
  unknown falls back to the default persona/voice. `scenario_id`
  (`STORY-03-04`) selects a structured scenario from `scenarios.py`
  (`STORY-03-03`) — its prompt addendum is layered on top of the
  persona base, and the character proactively speaks its
  `opening_line_hint` before the session starts listening. Omitted or
  unknown falls back to freeform (today's behavior, unchanged). Both
  `character_id`/`scenario_id` are ignored on reconnect (the original
  session's character/scenario is already bound; no opening line replay).
  `english_level` (`A2`/`B1`/`B2`/`C1`/`native`, `persona.ENGLISH_LEVELS`)
  sets how simply the character speaks; omitted or unknown -> `B1`.
  `use_memory: false` starts without the character's memory of past
  sessions (default true; the session is still remembered afterwards).
  Both are ignored on reconnect too.
- `{"type": "session_start", "proto_version": 1, "resume_session_id": "...", "english_level": "<optional>", "use_memory": <optional bool>}`
  Continues a past conversation (ADR-0015) under its own id: character,
  scenario (no opening line) and stored level come from its row; history
  is rebuilt from its turns. Closes with 4404 if there is no such row. A
  plain reconnect with a `session_id` the server no longer holds in memory
  resumes the same way.
- Interview characters (`session_mode: "interview"`, EPIC-10 / ADR-0016):
  `session_start` may carry `"interview": {"count": 10, "max_followups": 1,
  "categories": ["api", ...]}` (all optional, config defaults otherwise).
  Questions come from the prep base; if it can't be read the server sends
  `error` and closes with 4503. Scenario and memory are ignored.
- `{"type": "session_end"}` — clean end, releases the session for good.
- (binary) mic audio chunks, any size, PCM16/16kHz/mono.

Server -> Client:
- `{"type": "session_ready", "proto_version": 1, "session_id": "...", "reconnected": bool}`
- `{"type": "session_state", "state": "listening" | "processing" | "speaking"}`
- `{"type": "session_state", "state": "preparing", "expected_s": 9.5, "model_loading": bool}`:
  only at session start, only if the LLM prewarm takes longer than 0.5s.
  The mic stays closed until the next state; `expected_s` is a rough
  estimate for a progress bar, and `model_loading` means the model itself
  is being loaded into memory.
- `{"type": "transcript_final", "text": "..."}`
- `{"type": "response_text_chunk", "text": "...", "sentence_index": N}`
- `{"type": "audio_chunk_boundary", "phase": "start" | "end", "sentence_index": N}`
  (binary TTS PCM16 chunks stream between a "start" and its "end" — a
  scenario's opening line uses this same shape, sent right after
  `session_ready`/before the first `listening` state, so the client
  doesn't need a separate code path for it)
- Interview mode only: `session_ready` gets `"interview": {"index", "count",
  "finished"}`; `{"type": "interview_progress", "index", "count",
  "finished"}` when the current question changes; `{"type":
  "interview_finished"}` after the closing line has played — the server
  then ends the session itself (`session_ended` follows).
- `{"type": "error", "message": "..."}` — non-fatal unless followed by close.
- `{"type": "session_ended"}`

A server restart mid-session loses in-memory state, but the client's
reconnect then resumes the conversation from the DB (see above). Full
reconnect UX is `EPIC-08`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from app.audio_utils import pcm16_to_wav_bytes
from app.config import resolve_repo_path
from app.interview.builder import InterviewUnavailable, build_interview, interview_options, state_from_rows
from app.interview.prompts import render_interviewer_prompt
from app.interview.session import InterviewState
from app.conversation_engine import ConversationEngineError, split_sentences
from app.persona import (
    DEFAULT_ENGLISH_LEVEL,
    DEFAULT_SYSTEM_PROMPT,
    ENGLISH_LEVELS,
    render_level_addendum,
    render_memory_addendum,
    render_scenario_addendum,
    render_system_prompt,
)
from app.session_registry import SessionConflictError
from app.stt_service import NOISE_PHRASES, STTServiceError, phrase_key
from app.tts_service import TTSServiceError, speakable_text
from app.turn_detection import looks_incomplete
from app.vad_service import TurnSegmenter

logger = logging.getLogger("ai_english.ws_session")

PROTO_VERSION = 1
MIN_UTTERANCE_BYTES = 9600  # ~0.3s at 16kHz/16-bit mono — filters VAD blips
INBOUND_GAP_LOG_S = 2.0
PCM_BYTES_PER_SECOND = 32000  # 16kHz * 16-bit mono
# Network transit + client AudioTrack buffering on top of the pure audio
# duration, before the phone is actually silent again.
PLAYBACK_TAIL_MARGIN_S = 0.4
# whisper.cpp's non-speech markers ("[BLANK_AUDIO]", "(music)", ...).
NON_SPEECH_MARKER = re.compile(r"\[[^\]]*\]|\([^)]*\)|\*[^*]*\*")

# A whole utterance this short that is only a stock filler is noise that
# whisper "heard" (`stt_service.NOISE_PHRASES`; medium.en returned
# [BLANK_AUDIO] on the same keyboard clicks). A filler closing longer
# speech is handled in `STTService.transcribe`.
HALLUCINATION_MAX_S = 2.5


def is_noise_hallucination(transcript: str, audio_bytes: int) -> bool:
    if audio_bytes / PCM_BYTES_PER_SECOND > HALLUCINATION_MAX_S:
        return False
    key = phrase_key(transcript)
    return not key or key in NOISE_PHRASES


DEBUG_AUDIO_DIR = resolve_repo_path("server/data/debug_audio")
# Session-start prewarm: waits shorter than this aren't shown to the user;
# past PREPARE_MAX_S the session opens anyway (the first reply then waits).
PREPARE_SILENT_S = 0.5
PREPARE_MAX_S = 90.0


def _save_debug_audio(session_id: str, pcm: bytes) -> str | None:
    try:
        DEBUG_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        path = DEBUG_AUDIO_DIR / f"{session_id[:8]}_{time.strftime('%H%M%S')}_{len(pcm) // 32}ms.wav"
        path.write_bytes(pcm16_to_wav_bytes(pcm))
        return str(path)
    except OSError:
        return None


class PlaybackClock:
    """Estimates when the client finishes *playing* the TTS audio sent so
    far. TTS synthesizes faster than real time, so the server is done
    sending well before the phone is done speaking — reopening the mic
    at send-end let the phone's own speaker output (and the user
    answering over it) leak into the next turn (STORY-05-11)."""

    def __init__(self) -> None:
        self._until = 0.0

    def add(self, pcm_bytes: int) -> None:
        self._until = max(self._until, time.monotonic()) + pcm_bytes / PCM_BYTES_PER_SECOND

    async def wait_drained(self) -> None:
        remaining = self._until + PLAYBACK_TAIL_MARGIN_S - time.monotonic()
        if remaining > 0:
            await asyncio.sleep(remaining)


def turn_patience_s(config: dict[str, Any], english_level: str) -> float:
    """Extra silence after a VAD pause before a finished-looking utterance
    counts as the end of the turn (`vad.patience_ms_by_level`)."""
    by_level = config["vad"].get("patience_ms_by_level") or {}
    return max(0.0, float(by_level.get(english_level, 0)) / 1000)


def compose_system_prompt(
    preset: Any, scenario: Any, english_level: str, memory_summary: str | None
) -> str:
    """Persona (or the default one) + scenario addendum + English level +
    memory of past sessions, in that order."""
    if preset is not None and preset.session_mode == "interview":
        # EPIC-10: no proactive contract, no scenario, no memory — the
        # interviewer has its own template (app/interview/prompts.py).
        prompt = preset.system_prompt_override or render_interviewer_prompt(preset.name, preset.role_description)
        return f"{prompt}\n\n{render_level_addendum(english_level)}"
    if preset is not None:
        prompt = preset.system_prompt_override or render_system_prompt(
            preset.name, preset.role_description, preset.correction_style
        )
    else:
        prompt = DEFAULT_SYSTEM_PROMPT
    if scenario is not None:
        addendum = render_scenario_addendum(
            scenario.title, scenario.character_role_prompt_addendum, scenario.goal
        )
        prompt = f"{prompt}\n\n{addendum}"
    prompt = f"{prompt}\n\n{render_level_addendum(english_level)}"
    if memory_summary:
        prompt = f"{prompt}\n\n{render_memory_addendum(memory_summary)}"
    return prompt


async def handle_ws_session(websocket: WebSocket) -> None:
    app = websocket.app
    registry = app.state.session_registry
    conversation_engine = app.state.conversation_engine
    stt_service = app.state.stt_service
    tts_service = app.state.tts_service
    db = app.state.db

    await websocket.accept()

    # The client's mic keeps streaming across a reconnect, and OkHttp
    # queues frames sent before the handshake completes — so stale audio
    # can arrive ahead of `session_start`. Skip binary frames until it does.
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        if message.get("text") is not None:
            break
    first = json.loads(message["text"])
    if first.get("type") != "session_start":
        await websocket.send_json({"type": "error", "message": "expected session_start as first message"})
        await websocket.close(code=4400)
        return

    requested_session_id = first.get("session_id")
    resume_id = first.get("resume_session_id")
    if resume_id and not requested_session_id:
        if await db.get_session(resume_id) is None:
            await websocket.send_json({"type": "error", "message": f"conversation {resume_id!r} not found"})
            await websocket.close(code=4404)
            return
        requested_session_id = resume_id
    try:
        claim = registry.try_claim(requested_session_id, owner=websocket)
    except SessionConflictError as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close(code=4409)
        return

    session_id = claim.session_id
    if claim.superseded_owner is not None:
        logger.info("ws_session_taken_over", extra={"session_id": session_id})
        asyncio.create_task(_close_quietly(claim.superseded_owner))
    if claim.evicted_session_id:
        conversation_engine.end_session(claim.evicted_session_id)
        logger.info("ws_session_evicted_stale", extra={"session_id": claim.evicted_session_id})

    preset = None
    scenario = None
    resumed = False
    interview: InterviewState | None = None
    opening_text: str | None = None  # spoken before the first `listening`
    interviews = app.state.interviews
    memory_since = None  # resume time: the memory update only reads newer turns
    session_row = await db.get_session(session_id) if requested_session_id else None
    if claim.is_reconnect:
        # Restore which character this session was bound to, so TTS
        # voice selection stays consistent across a reconnect. Scenario
        # opening lines don't replay on reconnect (already spoken/in
        # history), so scenario isn't restored here.
        if session_row and session_row.get("character_id"):
            preset = app.state.preset_store.get(session_row["character_id"])
        english_level = _level((session_row or {}).get("english_level"))
        use_memory = None
        if preset is not None and preset.session_mode == "interview":
            interview = interviews.get(session_id)
    else:
        resumed = session_row is not None
        row = session_row or {}
        character_id = row.get("character_id") if resumed else first.get("character_id")
        if character_id:
            preset = app.state.preset_store.get(character_id)
            if preset is None:
                logger.warning("ws_unknown_character_id", extra={"character_id": character_id})

        is_interview = preset is not None and preset.session_mode == "interview"
        scenario_id = None if is_interview else (row.get("scenario_id") if resumed else first.get("scenario_id"))
        if scenario_id:
            scenario = app.state.scenario_store.get(scenario_id)
            if scenario is None:
                logger.warning("ws_unknown_scenario_id", extra={"scenario_id": scenario_id})

        english_level = first.get("english_level")
        if english_level not in ENGLISH_LEVELS:
            if english_level is not None:
                logger.warning("ws_unknown_english_level", extra={"english_level": english_level})
            english_level = _level(row.get("english_level"))

        stored_memory = row.get("use_memory")
        use_memory = first.get("use_memory", True if stored_memory is None else bool(stored_memory)) is not False
        memory_summary = None
        if preset is not None and preset.memory_enabled and use_memory and not is_interview:
            memory = await db.get_character_memory(preset.id)
            memory_summary = memory.get("rolling_summary") if memory else None

        system_prompt = compose_system_prompt(preset, scenario, english_level, memory_summary)
        if resumed:
            turns = await db.get_transcript(session_id)
            restored, mode = conversation_engine.restore_history(system_prompt, turns, row.get("summary"))
            if is_interview and (rows := await db.get_interview_items(session_id)):
                interview = state_from_rows(
                    preset.name, rows, interview_options(app.state.config, first.get("interview"))["max_followups"]
                )
                opening_text = interview.resume_line()
                restored = restored + [{"role": "assistant", "content": opening_text}]
            conversation_engine.start_session(
                session_id, system_prompt=system_prompt, restored=restored if len(restored) > 1 else None
            )
            memory_since = datetime.now(timezone.utc).isoformat()
            await db.reopen_session(session_id)
            logger.info(
                "conversation_resumed" if mode != "truncated" else "conversation_resume_truncated",
                extra={"session_id": session_id, "mode": mode, "turns": len(turns), "messages": len(restored) - 1},
            )
        else:
            if is_interview:
                try:
                    interview = await build_interview(
                        app, preset.name, interview_options(app.state.config, first.get("interview"))
                    )
                except InterviewUnavailable as exc:
                    logger.warning("interview_unavailable", extra={"session_id": session_id, "error": str(exc)})
                    registry.end(session_id)
                    await websocket.send_json({"type": "error", "message": f"interview unavailable: {exc}"})
                    await websocket.close(code=4503)
                    return
                opening_text = interview.opening()
            elif scenario is not None:
                opening_text = scenario.opening_line_hint
            conversation_engine.start_session(
                session_id,
                system_prompt=system_prompt,
                opening_message=opening_text,
            )
            await db.create_session(
                session_id,
                character_id=preset.id if preset else None,
                scenario_id=scenario.id if scenario else None,
                english_level=english_level,
                use_memory=use_memory,
            )
            if interview is not None:
                interview.take_changes()
                await db.create_interview_items(session_id, [i.as_row() for i in interview.items])

    logger.info(
        "ws_session_started",
        extra={
            "session_id": session_id,
            "reconnected": claim.is_reconnect,
            "resumed": resumed,
            "english_level": english_level,
            "use_memory": use_memory,
            "turn_patience_s": turn_patience_s(app.state.config, english_level),
        },
    )
    if interview is not None:
        interviews[session_id] = interview
        await _save_interview_changes(db, session_id, interview)
    ready = {
        "type": "session_ready",
        "proto_version": PROTO_VERSION,
        "session_id": session_id,
        "reconnected": claim.is_reconnect,
    }
    if interview is not None:
        ready["interview"] = _interview_progress(interview)
    await websocket.send_json(ready)

    segmenter = TurnSegmenter(app.state.config)
    voice_id = tts_service.resolve(preset.tts_engine, preset.tts_voice_id) if preset else None
    clean_end = False
    turn_task: asyncio.Task | None = None
    clock = PlaybackClock()

    # Smart turn (`turn_detection.py`): a VAD pause doesn't end the turn
    # by itself — the utterance is transcribed first, and if it looks
    # unfinished the turn is held open for `hold_s` so the user can carry
    # on. Speech resuming during the hold (or during that STT call)
    # cancels the decision; the next pause re-decides on all the audio
    # so far, concatenated.
    hold_s = app.state.config["vad"].get("incomplete_hold_ms", 2000) / 1000
    patience_s = turn_patience_s(app.state.config, english_level)
    stt_context = bool(app.state.config["stt"].get("context_prompt", False))
    save_utterances = bool(app.state.config["stt"].get("save_utterances", False))
    pending_audio = bytearray()
    decide_task: asyncio.Task | None = None
    finish_requested = asyncio.Event()
    finish_waiter: asyncio.Future | None = None

    async def decide_turn() -> None:
        try:
            await _decide_turn()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ws_turn_decide_error", extra={"session_id": session_id})

    async def _decide_turn() -> None:
        nonlocal turn_task
        paused_at = time.monotonic()
        audio = bytes(pending_audio)
        try:
            stt_prompt = conversation_engine.last_reply(session_id) if stt_context else None
            transcript = await stt_service.transcribe(pcm16_to_wav_bytes(audio), prompt=stt_prompt)
        except STTServiceError as exc:
            logger.warning("ws_turn_stt_failed", extra={"session_id": session_id, "error": str(exc)})
            await websocket.send_json({"type": "error", "message": f"transcription failed: {exc}"})
            pending_audio.clear()
            return
        transcript = NON_SPEECH_MARKER.sub("", transcript).strip()
        if transcript and is_noise_hallucination(transcript, len(audio)):
            logger.info("ws_turn_hallucination_dropped", extra={"session_id": session_id, "transcript": transcript})
            transcript = ""
        if not transcript:
            # VAD heard "speech" that STT found empty. Kept on disk to tell
            # silence/echo/corrupted audio apart (STORY-05-11: after a
            # reconnect, 8 utterances in a row came back empty).
            path = _save_debug_audio(session_id, audio)
            logger.info("ws_turn_non_speech_dropped", extra={"session_id": session_id, "audio_path": path})
            pending_audio.clear()
            return
        held = looks_incomplete(transcript)
        if held:
            logger.info("ws_turn_held_incomplete", extra={"session_id": session_id, "transcript": transcript})
            await asyncio.sleep(hold_s)
        elif (remaining := patience_s - (time.monotonic() - paused_at)) > 0:
            # Finished-looking text still gets the level's extra pause
            # (the STT call above already counts towards it): learners
            # stop mid-thought to find a word, and whisper puts a period
            # on almost anything (2026-11-11 phone test).
            await asyncio.sleep(remaining)
        pending_audio.clear()
        if save_utterances:
            # Real phone speech for offline STT evaluation (`bench.stt_eval`
            # takes fixtures; this log line has what's needed to build one).
            logger.info(
                "ws_turn_audio_saved",
                extra={"session_id": session_id, "audio_path": _save_debug_audio(session_id, audio),
                       "transcript": transcript, "stt_prompt": stt_prompt},
            )
        turn_task = asyncio.create_task(run_turn(audio, transcript, held))

    async def run_turn(utterance: bytes, transcript: str, held: bool) -> None:
        try:
            await _handle_turn(
                websocket, session_id, utterance,
                conversation_engine, stt_service, tts_service, db,
                voice_id, clock, transcript=transcript, held=held, interview=interview,
            )
            # The turn task stays alive (so mic audio keeps being
            # dropped) until the phone has actually finished speaking.
            await clock.wait_drained()
            if interview is not None and interview.finished:
                # The closing line has been spoken: end the session the
                # same way a client `session_end` would (next loop pass).
                finish_requested.set()
                await websocket.send_json({"type": "interview_finished"})
                return
            await websocket.send_json({"type": "session_state", "state": "listening"})
        except asyncio.CancelledError:
            raise
        except Exception:
            # The receive loop notices a dead socket on its own; this just
            # keeps a failed turn from vanishing silently inside the task.
            logger.exception("ws_turn_error", extra={"session_id": session_id})
        finally:
            # Audio that arrived mid-turn was dropped (see below), so the
            # VAD must not carry a half-seen utterance into the next turn.
            segmenter.reset()

    try:
        await _wait_until_prepared(websocket, conversation_engine, session_id)
        if opening_text and not claim.is_reconnect:
            await websocket.send_json({"type": "session_state", "state": "speaking"})
            sent = await _speak_text(websocket, tts_service, session_id, opening_text, voice_id, clock)
            await db.add_turn(session_id, "assistant", opening_text,
                              question_idx=interview.index if interview is not None else None,
                              audio_ms=_audio_ms(sent))
            await clock.wait_drained()
            segmenter.reset()
        if interview is not None and interview.finished:
            finish_requested.set()  # resumed an interview with nothing left to ask
            await websocket.send_json({"type": "interview_finished"})
        await websocket.send_json({"type": "session_state", "state": "listening"})
        # The client mic streams continuously, so a gap in inbound frames
        # means the network path stalled — logged to pin down the
        # unexplained client-side reconnects (STORY-05-11).
        last_frame_at = time.monotonic()
        finish_waiter = asyncio.ensure_future(finish_requested.wait())
        while True:
            # Wait for a frame *or* the interview's own end, so a client
            # that sends nothing (e.g. muted) can't hold a finished
            # interview open.
            receive_task = asyncio.ensure_future(websocket.receive())
            await asyncio.wait({receive_task, finish_waiter}, return_when=asyncio.FIRST_COMPLETED)
            if finish_requested.is_set():
                receive_task.cancel()
                clean_end = True
                break
            message = receive_task.result()
            if message["type"] == "websocket.disconnect":
                logger.info(
                    "ws_client_disconnect",
                    extra={
                        "session_id": session_id,
                        "code": message.get("code"),
                        "since_last_frame_s": round(time.monotonic() - last_frame_at, 1),
                    },
                )
                break

            if (data := message.get("bytes")) is not None:
                now = time.monotonic()
                if now - last_frame_at > INBOUND_GAP_LOG_S:
                    logger.warning(
                        "ws_inbound_gap",
                        extra={"session_id": session_id, "gap_s": round(now - last_frame_at, 1)},
                    )
                last_frame_at = now
                # A turn runs as its own task so this loop keeps reading
                # the socket throughout it — otherwise the inbound queue
                # fills with mic audio, websockets stops reading frames,
                # client pings go unanswered and a long reply drops the
                # connection (STORY-05-11). Mic audio during a turn is
                # discarded: turn-taking is non-interruptible (no barge-in,
                # EPIC-06), and queuing it would replay speaker echo or
                # mid-reply speech as a phantom next turn.
                if turn_task is not None and not turn_task.done():
                    continue
                for event in segmenter.feed(data):
                    if event["type"] == "speech_start":
                        if decide_task is not None and not decide_task.done():
                            decide_task.cancel()  # user carried on — not a turn end
                    elif event["type"] == "speech_end" and len(event["audio"]) >= MIN_UTTERANCE_BYTES:
                        pending_audio.extend(event["audio"])
                        decide_task = asyncio.create_task(decide_turn())
                continue

            if (text := message.get("text")) is not None:
                payload = json.loads(text)
                if payload.get("type") == "session_end":
                    clean_end = True
                    break

    except WebSocketDisconnect:
        logger.info("ws_session_disconnected", extra={"session_id": session_id})
    except Exception:
        logger.exception("ws_session_error", extra={"session_id": session_id})
        try:
            await websocket.send_json({"type": "error", "message": "internal server error"})
        except Exception:
            pass
    finally:
        if finish_waiter is not None:
            finish_waiter.cancel()
        if decide_task is not None and not decide_task.done():
            decide_task.cancel()
        if turn_task is not None and not turn_task.done():
            turn_task.cancel()
            try:
                await turn_task
            except (asyncio.CancelledError, Exception):
                pass
        if clean_end:
            interviews.pop(session_id, None)
            registry.end(session_id)
            history = conversation_engine.history(session_id)
            conversation_engine.end_session(session_id)
            await db.end_session(session_id)
            # Fire-and-forget: fully off the session-teardown path, let
            # alone the live conversation's — the client doesn't wait on
            # this to get its session_ended ack.
            asyncio.create_task(_after_session(app, session_id, history, preset, memory_since))
            try:
                await websocket.send_json({"type": "session_ended"})
            except Exception:
                pass
            logger.info("ws_session_ended_clean", extra={"session_id": session_id})
        else:
            registry.release(session_id, claim.generation)
            logger.info("ws_session_released_for_reconnect", extra={"session_id": session_id})


def _level(stored: str | None) -> str:
    return stored if stored in ENGLISH_LEVELS else DEFAULT_ENGLISH_LEVEL


async def _after_session(app, session_id: str, history: list[dict] | None, preset, memory_since: str | None) -> None:
    """Wrap-up (title, plus notes when a resume would need them, ADR-0015)
    first, while Ollama still has this history cached; then the character
    memory, which re-reads the transcript anyway."""
    db, engine = app.state.db, app.state.conversation_engine
    try:
        turns = await db.get_transcript(session_id)
        if history and any(t["role"] == "user" for t in turns):
            with_notes = not engine.fits_context(
                history[:1] + [{"role": t["role"], "content": t["text"]} for t in turns]
            )
            title, notes = await engine.wrap_up(session_id, history, with_notes)
            if title or notes:
                await db.save_wrap_up(session_id, title, notes, len(turns))
        if preset is not None and preset.memory_enabled:
            await app.state.character_memory_service.update_after_session(
                session_id, preset.id, preset.name, since=memory_since
            )
    except Exception:
        logger.exception("ws_after_session_error", extra={"session_id": session_id})


async def _wait_until_prepared(websocket, conversation_engine, session_id: str) -> None:
    """Hold the mic closed until the session-start prewarm is done, so the
    first reply doesn't queue behind it (cold: 6-16s; warm: ~0.4s). Short
    waits pass silently; a longer one is announced as the `preparing`
    state with a time estimate the client turns into a progress bar."""
    task = conversation_engine.prewarm_pending(session_id)
    if task is None:
        return
    started = time.monotonic()
    done, _ = await asyncio.wait({task}, timeout=PREPARE_SILENT_S)
    if done:
        return
    loaded = await conversation_engine.model_loaded()
    expected_s = conversation_engine.estimate_prepare_s(session_id, loaded)
    await websocket.send_json({
        "type": "session_state", "state": "preparing",
        "expected_s": expected_s, "model_loading": not loaded,
    })
    # shield: a timeout must not cancel the prewarm itself.
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=PREPARE_MAX_S)
    except asyncio.TimeoutError:
        logger.warning("ws_prepare_timeout", extra={"session_id": session_id})
    logger.info(
        "ws_session_prepared",
        extra={"session_id": session_id, "wait_s": round(time.monotonic() - started, 2),
               "expected_s": expected_s, "model_was_loaded": loaded},
    )


async def _close_quietly(websocket) -> None:
    """Close a superseded (likely half-open) socket without letting a dead
    peer stall the caller."""
    try:
        await asyncio.wait_for(websocket.close(code=4001), timeout=5)
    except Exception:
        pass


async def _speak_sentence(
    websocket, tts_service, session_id, text, sentence_index, voice_id, clock: PlaybackClock | None = None
) -> tuple[float | None, int]:
    """Returns the monotonic time the first audio chunk was sent (None if
    none was) and how many PCM bytes were sent."""
    await websocket.send_json(
        {"type": "response_text_chunk", "text": text, "sentence_index": sentence_index}
    )
    await websocket.send_json(
        {"type": "audio_chunk_boundary", "phase": "start", "sentence_index": sentence_index}
    )
    first_audio_at = None
    sent_bytes = 0
    try:
        async for pcm_chunk in tts_service.synthesize_stream(text, voice=voice_id):
            await websocket.send_bytes(pcm_chunk)
            sent_bytes += len(pcm_chunk)
            if clock is not None:
                clock.add(len(pcm_chunk))
            if first_audio_at is None:
                first_audio_at = time.monotonic()
    except TTSServiceError as exc:
        logger.warning("ws_turn_tts_failed", extra={"session_id": session_id, "error": str(exc)})
        await websocket.send_json({"type": "error", "message": f"synthesis failed: {exc}"})
    await websocket.send_json(
        {"type": "audio_chunk_boundary", "phase": "end", "sentence_index": sentence_index}
    )
    return first_audio_at, sent_bytes


def _audio_ms(pcm_bytes: int) -> int:
    return round(pcm_bytes * 1000 / PCM_BYTES_PER_SECOND)


async def _speak_text(websocket, tts_service, session_id, text, voice_id, clock=None) -> int:
    """Split already-known static text (a scenario's opening line, not a
    live LLM stream) into the same sentence-chunked TTS shape as a normal
    reply, so the client needs no separate code path for it. Returns the
    PCM bytes sent."""
    total = 0
    for i, sentence in enumerate(split_sentences(text)):
        _, sent = await _speak_sentence(websocket, tts_service, session_id, sentence, i, voice_id, clock)
        total += sent
    return total


def _interview_progress(interview: InterviewState) -> dict:
    return {"index": interview.index, "count": interview.count, "finished": interview.finished}


async def _save_interview_changes(db, session_id: str, interview: InterviewState) -> None:
    for item in interview.take_changes():
        await db.set_interview_item_status(session_id, item.idx, item.status)


async def _handle_turn(
    websocket, session_id, utterance_pcm, conversation_engine, stt_service, tts_service, db,
    voice_id=None, clock: PlaybackClock | None = None,
    transcript: str | None = None, held: bool = False, interview: InterviewState | None = None,
) -> None:
    """`transcript` is passed in when the smart-turn decision already ran
    STT on this utterance; timings are then relative to the decision,
    not to VAD speech_end."""
    t0 = time.monotonic()
    await websocket.send_json({"type": "session_state", "state": "processing"})

    if transcript is None:
        try:
            transcript = await stt_service.transcribe(pcm16_to_wav_bytes(utterance_pcm))
        except STTServiceError as exc:
            logger.warning("ws_turn_stt_failed", extra={"session_id": session_id, "error": str(exc)})
            await websocket.send_json({"type": "error", "message": f"transcription failed: {exc}"})
            return
        transcript = NON_SPEECH_MARKER.sub("", transcript).strip()
    if not transcript:
        logger.info("ws_turn_non_speech_dropped", extra={"session_id": session_id})
        return

    await websocket.send_json({"type": "transcript_final", "text": transcript})
    plan = interview.plan_turn(transcript) if interview is not None else None
    await db.add_turn(session_id, "user", transcript, question_idx=plan.question_idx if plan else None,
                      audio_ms=_audio_ms(len(utterance_pcm)))
    await websocket.send_json({"type": "session_state", "state": "speaking"})
    t_stt = time.monotonic()
    t_first_sentence = t_first_audio = None

    if plan is not None and plan.kind == "scripted":
        # Interview: skip / repeat, or "okay" + next question — no LLM.
        sent = await _speak_text(websocket, tts_service, session_id, plan.scripted_text, voice_id, clock)
        await conversation_engine.append_exchange(session_id, transcript, plan.scripted_text)
        await db.add_turn(session_id, "assistant", plan.scripted_text, question_idx=interview.index,
                          audio_ms=_audio_ms(sent))
        await _after_interview_turn(websocket, db, session_id, interview, plan)
        logger.info("ws_turn_timing", extra={
            "session_id": session_id, "interview_command": plan.command or "ack_next",
            "interview_index": interview.index,
            "turn_total_s": round(time.monotonic() - t0, 3), "user_words": len(transcript.split()),
        })
        return

    llm_text = plan.llm_text if plan is not None else transcript
    model_reply: list[str] = []

    def reply_suffix(reply: str) -> str | None:
        model_reply.append(reply)
        return interview.finish_reply(plan, reply)

    try:
        sentence_index = 0
        reply_bytes = 0
        full_reply = ""
        async for event in conversation_engine.generate_reply(
            session_id, llm_text, reply_suffix=reply_suffix if plan is not None else None
        ):
            if event["type"] in ("done", "cancelled"):
                full_reply = event.get("full_text", "")
                continue
            if event["type"] != "sentence":
                continue
            spoken = speakable_text(event["text"])
            if not spoken:
                continue  # e.g. a sentence that was only emoji
            if t_first_sentence is None:
                t_first_sentence = time.monotonic()
            sent_at, sent = await _speak_sentence(
                websocket, tts_service, session_id, spoken, sentence_index, voice_id, clock
            )
            reply_bytes += sent
            if t_first_audio is None:
                t_first_audio = sent_at
            sentence_index += 1
        if full_reply.strip():
            await db.add_turn(session_id, "assistant", full_reply,
                              question_idx=interview.index if interview is not None else None,
                              audio_ms=_audio_ms(reply_bytes))
        if plan is not None:
            await _after_interview_turn(websocket, db, session_id, interview, plan)
        # Per-turn latency breakdown, all relative to VAD speech_end
        # (excludes the VAD silence cutoff itself and network transit).
        since = lambda t: round(t - t0, 3) if t is not None else None  # noqa: E731
        logger.info(
            "ws_turn_timing",
            extra={
                "session_id": session_id,
                "utterance_s": round(len(utterance_pcm) / 32000, 2),
                "held_incomplete": held,
                "stt_s": since(t_stt),
                "llm_first_sentence_s": since(t_first_sentence),
                "first_audio_s": since(t_first_audio),
                "turn_total_s": since(time.monotonic()),
                "sentences": sentence_index,
                "user_words": len(transcript.split()),
                "reply_words": len(full_reply.split()),
                **({"interview_index": interview.index, "interview_command": plan.command,
                    "followups_used": interview.followups_used} if plan is not None else {}),
            },
        )
    except ConversationEngineError as exc:
        logger.warning("ws_turn_llm_failed", extra={"session_id": session_id, "error": str(exc)})
        await websocket.send_json({"type": "error", "message": f"generation failed: {exc}"})


async def _after_interview_turn(websocket, db, session_id: str, interview: InterviewState, plan) -> None:
    await _save_interview_changes(db, session_id, interview)
    if interview.index != plan.question_idx or interview.finished:
        await websocket.send_json({"type": "interview_progress", **_interview_progress(interview)})
