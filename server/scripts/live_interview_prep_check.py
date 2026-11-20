"""EPIC-10 / STORY-10-03: live check of the prep-base interviewer against
the real server (VAD -> STT -> gemma -> TTS).

Drives `daniel_interviewer` with Piper-synthesised candidate answers,
including the voice commands (repeat, skip), and runs until the server
ends the interview on its own. Prints the transcript with question
indices from SQLite afterwards.

    uv run python scripts/live_interview_prep_check.py [--count 4] [--followups 1]

Needs the server running (it uses the shared Ollama — not during a voice
session), the prep container and translated questions.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import time

import websockets
from _auth import auth_headers

from live_persona_spotcheck import DB_PATH, VOICE_CONFIG, VOICE_MODEL, send_utterance, synthesize_to_pcm16k
from piper.voice import PiperVoice

ANSWERS = [
    "Sure. I'm a backend developer with twelve years in e-commerce. I started with Magento, and for the last "
    "three years I worked at Rezolve on integrations, a Python PIM and some Java microservices.",
    "Mostly because it was the simplest option, and it worked well with the code we already had.",
    "Can you repeat the question?",
    "Okay. I would start by measuring where the time goes, then add caching, and then look at the slowest "
    "database queries and the indexes.",
    "We used Redis and the full page cache, and we warmed the cache after every deploy.",
    "Skip this one.",
    "I would use idempotency keys and a queue, so every event is processed once, even if it is delivered twice.",
    "Yes, we stored the key in the database with a unique index and ignored duplicates.",
] + ["I think that's a reasonable approach, because it keeps the system simple and easy to support."] * 10


async def run(url: str, count: int, followups: int) -> str | None:
    voice = PiperVoice.load(str(VOICE_MODEL), str(VOICE_CONFIG))
    t0 = time.time()
    session_id = None
    async with websockets.connect(url, max_size=None, additional_headers=auth_headers()) as ws:
        await ws.send(json.dumps({"type": "session_start", "proto_version": 1, "character_id": "daniel_interviewer",
                                  "english_level": "B2",
                                  "interview": {"count": count, "max_followups": followups}}))
        listening = asyncio.Event()
        finished = asyncio.Event()

        async def sender():
            for i, line in enumerate(ANSWERS):
                await listening.wait()
                if finished.is_set():
                    return
                listening.clear()
                print(f"\n[{time.time() - t0:6.1f}s] >>> USER {i}: {line}")
                await send_utterance(ws, synthesize_to_pcm16k(voice, line))
            await ws.send(json.dumps({"type": "session_end"}))

        task = asyncio.create_task(sender())
        async for raw in ws:
            if isinstance(raw, bytes):
                continue
            ev = json.loads(raw)
            kind = ev.get("type")
            stamp = f"[{time.time() - t0:6.1f}s]"
            if kind == "session_ready":
                session_id = ev["session_id"]
                print(stamp, ev)
            elif kind == "response_text_chunk":
                print(stamp, "DANIEL:", ev["text"])
            elif kind in ("transcript_final", "interview_progress", "interview_finished", "error", "session_ended"):
                print(stamp, ev)
            if kind == "interview_finished":
                finished.set()
            if kind == "session_state" and ev.get("state") == "listening":
                listening.set()
            if kind == "session_ended":
                break
        finished.set()
        listening.set()
        task.cancel()
    return session_id


def print_transcript(session_id: str) -> None:
    con = sqlite3.connect(DB_PATH)
    print("\n==== items ====")
    for row in con.execute("SELECT idx, question_id, status, question_en FROM interview_items WHERE session_id=? "
                           "ORDER BY idx", (session_id,)):
        print(row)
    print("\n==== turns ====")
    for role, text, qidx in con.execute("SELECT role, text, question_idx FROM turns WHERE session_id=? ORDER BY ts",
                                        (session_id,)):
        print(f"[q{qidx}] {role:9} {text}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8000/ws/session")
    parser.add_argument("--count", type=int, default=4)
    parser.add_argument("--followups", type=int, default=1)
    args = parser.parse_args()
    sid = asyncio.run(run(args.url, args.count, args.followups))
    if sid:
        print_transcript(sid)
