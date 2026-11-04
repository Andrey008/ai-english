"""STORY-03-01: live baseline-persona spot-check against the real
assembled server (VAD -> STT -> LLM -> TTS), not scripted LLM-only turns
like STORY-01-06's PoC check.

Drives one real WS session with a sequence of deliberately short/vague/
passive "user" lines (same stress-test intent as STORY-01-06), synthesized
to speech via Piper (so STT actually has to transcribe real audio, not a
text shortcut) and streamed in as if from a mic. Waits for each turn to
fully complete before sending the next line, so it's a real multi-turn
conversation, not one giant blob.

Usage:
    uv run python scripts/live_persona_spotcheck.py [--url ws://127.0.0.1:8000/ws/session]

Prints every server event live, then re-reads the full transcript back
from SQLite at the end for review (real persisted data, not just what
scrolled by).
"""
from __future__ import annotations

import argparse
import asyncio
import audioop
import json
import sqlite3
import sys
import time
from pathlib import Path

import websockets

SERVER_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SERVER_DIR.parent
sys.path.insert(0, str(SERVER_DIR))

from piper.voice import PiperVoice  # noqa: E402

VOICE_MODEL = REPO_ROOT / "poc" / "voices" / "en_US-lessac-medium.onnx"
VOICE_CONFIG = REPO_ROOT / "poc" / "voices" / "en_US-lessac-medium.onnx.json"
DB_PATH = SERVER_DIR / "data" / "ai_english.db"

TARGET_RATE = 16000
CHUNK_MS = 100
TRAILING_SILENCE_S = 1.5

# Deliberately short/vague/passive lines, mirroring STORY-01-06's
# scripted-passive-user stress test -- designed to tempt a dead-end
# "what would you like to talk about?" fallback if the contract is weak.
USER_LINES = [
    "Hi.",
    "Not much, really.",
    "I don't know.",
    "Sure, I guess.",
    "Maybe.",
    "It was okay.",
    "I'm not sure.",
    "Whatever you think.",
    "Yeah, kind of.",
    "I haven't thought about it.",
    "Not really my thing.",
    "I guess so.",
    "Same as always.",
    "Hard to say.",
    "That's fine.",
    "I don't really mind either way.",
    "Not much to add, honestly.",
    "I suppose.",
]


def synthesize_to_pcm16k(voice: PiperVoice, text: str) -> bytes:
    """Synthesize `text` with Piper (native rate) and downsample to
    16kHz mono PCM16 for the WS pipeline's expected input format."""
    native_rate = voice.config.sample_rate
    raw = b"".join(chunk.audio_int16_bytes for chunk in voice.synthesize(text))
    if native_rate == TARGET_RATE:
        return raw
    converted, _ = audioop.ratecv(raw, 2, 1, native_rate, TARGET_RATE, None)
    return converted


async def send_utterance(ws, pcm: bytes) -> None:
    chunk_bytes = int(TARGET_RATE * (CHUNK_MS / 1000) * 2)
    for i in range(0, len(pcm), chunk_bytes):
        await ws.send(pcm[i : i + chunk_bytes])
        await asyncio.sleep(CHUNK_MS / 1000)
    silence = b"\x00\x00" * int(TARGET_RATE * TRAILING_SILENCE_S)
    for i in range(0, len(silence), chunk_bytes):
        await ws.send(silence[i : i + chunk_bytes])
        await asyncio.sleep(CHUNK_MS / 1000)


async def run(url: str, character_id: str | None, scenario_id: str | None, num_lines: int) -> str:
    lines = USER_LINES[:num_lines]
    print(f"loading Piper voice from {VOICE_MODEL} ...")
    voice = PiperVoice.load(str(VOICE_MODEL), str(VOICE_CONFIG))
    print(f"synthesizing {len(lines)} passive-user lines ...")
    utterances = [synthesize_to_pcm16k(voice, line) for line in lines]

    t0 = time.time()
    session_id: str | None = None

    async with websockets.connect(url, max_size=None) as ws:
        start_msg = {"type": "session_start", "proto_version": 1}
        if character_id:
            start_msg["character_id"] = character_id
        if scenario_id:
            start_msg["scenario_id"] = scenario_id
        await ws.send(json.dumps(start_msg))

        idx = 0
        turn_done = asyncio.Event()

        async def sender():
            nonlocal idx
            await turn_done.wait()  # wait for session_ready before first turn
            for i, (line, pcm) in enumerate(zip(lines, utterances)):
                turn_done.clear()
                elapsed = round(time.time() - t0, 3)
                print(f"\n[{elapsed:>6}s] >>> USER TURN {i}: {line!r}")
                await send_utterance(ws, pcm)
                await turn_done.wait()
            await ws.send(json.dumps({"type": "session_end"}))

        send_task = asyncio.create_task(sender())

        async for raw in ws:
            elapsed = round(time.time() - t0, 3)
            if isinstance(raw, bytes):
                continue
            event = json.loads(raw)
            etype = event.get("type")
            if etype in ("response_text_chunk", "transcript_final", "error"):
                print(f"[{elapsed:>6}s] {event}")
            elif etype not in ("audio_chunk_boundary",):
                print(f"[{elapsed:>6}s] {event}")
            if etype == "session_ready":
                session_id = event["session_id"]
            if etype == "session_state" and event.get("state") == "listening":
                turn_done.set()
            if etype == "session_ended":
                break

        send_task.cancel()

    assert session_id is not None
    return session_id


def print_transcript(session_id: str) -> None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT role, text, ts FROM turns WHERE session_id = ? ORDER BY ts ASC", (session_id,)
    ).fetchall()
    conn.close()
    print(f"\n\n=== transcript for session {session_id} ({len(rows)} turns) ===")
    for row in rows:
        print(f"[{row['role']:>9}] {row['text']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8000/ws/session")
    parser.add_argument("--character-id", default=None)
    parser.add_argument("--scenario-id", default=None)
    parser.add_argument("--lines", type=int, default=len(USER_LINES))
    args = parser.parse_args()
    sid = asyncio.run(run(args.url, args.character_id, args.scenario_id, args.lines))
    print_transcript(sid)
