"""STORY-02-09: real end-to-end TTFA measurement against a running server.

Streams the same 5 real-voice clips STORY-01-02/01-05 used (2 passes),
back-to-back over one sustained WS session, and reports the TTFA
distribution across every VAD-detected utterance.

Design note: a first version of this script measured one "turn" per
clip and got nonsensical near-0s TTFA readings on later clips. Cause:
these are real ~14s spontaneous-speech clips with natural pauses long
enough to cross the VAD's silence threshold, so a single clip can
trigger *multiple* utterances/turns — assuming one clip == one turn
caused a later clip's receive loop to start by draining an already-
buffered tail-end event from a previous clip's second utterance,
producing a fake near-instant "TTFA". Fixed by running one continuous
background receiver over the whole session that tracks every
`processing -> first audio byte` interval as its own turn, with no
assumption about clip boundaries at all. Left documented here because
it's a real lesson for any future harness over this protocol, not just
this script.

TTFA = wall-clock from the server's `session_state: processing` event
(fired the instant VAD detects speech-end server-side) to the first
binary audio frame received back — matches STORY-01-05's "speech-end to
first response audio" definition.

Usage:
    uv run python scripts/measure_ttfa.py [--url ws://127.0.0.1:8000/ws/session]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
import wave
from pathlib import Path

import websockets

CLIPS_DIR = Path(__file__).resolve().parent.parent.parent / "poc" / "samples" / "real_voice"
CLIPS = [
    "clip1_normal.wav",
    "clip2_noise.wav",
    "clip3_fast.wav",
    "clip4_technical.wav",
    "clip5_freeform.wav",
]
PASSES = 2
SAMPLE_RATE = 16000
CHUNK_MS = 100
INTER_CLIP_GAP_S = 1.5
FINAL_DRAIN_S = 6.0


def load_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as wf:
        assert wf.getframerate() == SAMPLE_RATE and wf.getnchannels() == 1
        return wf.readframes(wf.getnframes())


async def main(url: str) -> None:
    results: list[dict] = []
    turn_log: list[dict] = []

    async with websockets.connect(url, max_size=None) as ws:
        await ws.send(json.dumps({"type": "session_start", "proto_version": 1}))
        print("session:", await ws.recv())
        await ws.recv()  # initial session_state: listening

        current: dict = {}
        stop = asyncio.Event()

        async def receiver():
            while not stop.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                if isinstance(raw, (bytes, bytearray)):
                    if "t_processing" in current and "t_first_audio" not in current:
                        current["t_first_audio"] = time.perf_counter()
                    continue
                event = json.loads(raw)
                etype = event.get("type")
                if etype == "session_state":
                    if event["state"] == "processing":
                        current.clear()
                        current["t_processing"] = time.perf_counter()
                    elif event["state"] == "listening" and "t_processing" in current:
                        if "t_first_audio" in current:
                            ttfa = current["t_first_audio"] - current["t_processing"]
                            results.append(round(ttfa, 3))
                            print(f"  turn #{len(results)} TTFA: {round(ttfa, 3)}s")
                        current.clear()
                elif etype == "response_text_chunk":
                    turn_log.append({"turn": len(results) + 1, "text": event["text"]})

        recv_task = asyncio.create_task(receiver())

        chunk_bytes = int(SAMPLE_RATE * (CHUNK_MS / 1000) * 2)
        silence_chunk = b"\x00\x00" * (chunk_bytes // 2)

        async def send_paced(data: bytes):
            for i in range(0, len(data), chunk_bytes):
                await ws.send(data[i : i + chunk_bytes])
                await asyncio.sleep(CHUNK_MS / 1000)

        for pass_idx in range(PASSES):
            for clip_name in CLIPS:
                print(f"\n=== streaming pass {pass_idx + 1}, {clip_name} ===")
                await send_paced(load_pcm(CLIPS_DIR / clip_name))
                # Real silence, actually sent (not just a local sleep) — the
                # VAD only sees time pass through bytes it's fed, so a gap
                # with nothing sent doesn't register as silence at all.
                gap_chunks = int(INTER_CLIP_GAP_S * 1000 / CHUNK_MS)
                for _ in range(gap_chunks):
                    await ws.send(silence_chunk)
                    await asyncio.sleep(CHUNK_MS / 1000)

        print(f"\nfinished streaming all clips, sending final silence + draining...")
        drain_chunks = int(FINAL_DRAIN_S * 1000 / CHUNK_MS)
        for _ in range(drain_chunks):
            await ws.send(silence_chunk)
            await asyncio.sleep(CHUNK_MS / 1000)
        await asyncio.sleep(1.0)
        stop.set()
        await recv_task

        await ws.send(json.dumps({"type": "session_end"}))
        try:
            async with asyncio.timeout(5):
                async for raw in ws:
                    if not isinstance(raw, (bytes, bytearray)) and json.loads(raw).get("type") == "session_ended":
                        break
        except (asyncio.TimeoutError, TimeoutError):
            pass

    print(f"\n=== TTFA distribution (n={len(results)} VAD-detected turns from "
          f"{PASSES * len(CLIPS)} clip streams) ===")
    print("all:", results)
    if results:
        print("median:", round(statistics.median(results), 3))
        srt = sorted(results)
        print("p90:", srt[min(len(srt) - 1, int(0.9 * len(srt)))])
        print("min/max:", min(results), max(results))

    out_path = Path(__file__).resolve().parent / "ttfa_results.json"
    out_path.write_text(json.dumps({"ttfa_s": results, "turns": turn_log}, indent=2))
    print("written to", out_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8000/ws/session")
    args = parser.parse_args()
    asyncio.run(main(args.url))
