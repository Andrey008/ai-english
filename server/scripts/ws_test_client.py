"""Throwaway WS test client (STORY-02-05) — drives a real session
manually against a running server, real audio in, real audio out.

Usage:
    uv run python scripts/ws_test_client.py [wav_path] [--url ws://127.0.0.1:8000/ws/session]

Streams a 16kHz mono WAV file's PCM as if it were live mic audio (with
real-time-ish pacing so VAD behaves as it would live), appends trailing
silence so VAD detects end-of-utterance, prints every server event, and
saves any returned TTS audio to `scripts/ws_test_output/`.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
import wave
from pathlib import Path

import websockets
from _auth import auth_headers

DEFAULT_WAV = Path(__file__).resolve().parent.parent.parent / "poc" / "samples" / "test_input.wav"
OUT_DIR = Path(__file__).resolve().parent / "ws_test_output"
CHUNK_MS = 100
SAMPLE_RATE = 16000
TRAILING_SILENCE_S = 1.5


def load_pcm(wav_path: Path) -> bytes:
    with wave.open(str(wav_path), "rb") as wf:
        assert wf.getframerate() == SAMPLE_RATE, f"expected {SAMPLE_RATE}Hz, got {wf.getframerate()}"
        assert wf.getnchannels() == 1, "expected mono"
        assert wf.getsampwidth() == 2, "expected 16-bit PCM"
        pcm = wf.readframes(wf.getnframes())
    silence = b"\x00\x00" * int(SAMPLE_RATE * TRAILING_SILENCE_S)
    return pcm + silence


async def run(wav_path: Path, url: str) -> None:
    OUT_DIR.mkdir(exist_ok=True)
    pcm = load_pcm(wav_path)
    chunk_bytes = int(SAMPLE_RATE * (CHUNK_MS / 1000) * 2)

    t0 = time.time()
    audio_chunks: dict[int, bytearray] = {}
    current_sentence: int | None = None

    async with websockets.connect(url, max_size=None, additional_headers=auth_headers()) as ws:
        await ws.send(json.dumps({"type": "session_start", "proto_version": 1}))

        async def sender():
            for i in range(0, len(pcm), chunk_bytes):
                await ws.send(pcm[i : i + chunk_bytes])
                await asyncio.sleep(CHUNK_MS / 1000)
            await asyncio.sleep(2.0)  # give the server time to finish the turn
            await ws.send(json.dumps({"type": "session_end"}))

        send_task = asyncio.create_task(sender())

        try:
            async for raw in ws:
                elapsed = round(time.time() - t0, 3)
                if isinstance(raw, bytes):
                    if current_sentence is not None:
                        audio_chunks.setdefault(current_sentence, bytearray()).extend(raw)
                    continue
                event = json.loads(raw)
                print(f"[{elapsed:>6}s] {event}")
                if event.get("type") == "audio_chunk_boundary":
                    current_sentence = event["sentence_index"] if event["phase"] == "start" else None
                if event.get("type") == "session_ended":
                    break
        finally:
            send_task.cancel()

    for idx, chunk in audio_chunks.items():
        out_path = OUT_DIR / f"sentence_{idx}.wav"
        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(bytes(chunk))
        print(f"wrote {out_path} ({len(chunk)} bytes)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("wav_path", nargs="?", type=Path, default=DEFAULT_WAV)
    parser.add_argument("--url", default="ws://127.0.0.1:8000/ws/session")
    args = parser.parse_args()
    asyncio.run(run(args.wav_path, args.url))
