"""Record the developer reading a benchmark script aloud (Mac mic).

    uv run --group bench python -m bench.record bench/scripts/smalltalk_b1.yaml

Writes `bench/fixtures/<name>/turnNN.wav` (16kHz mono PCM16 — the format
the live pipeline gets from the phone) and `fixture.json`. Resumable:
turns that already have audio are skipped unless listed in `--redo`.
The fixture is gitignored — it's the developer's voice, and the repo is
public.

Terminal needs microphone access (System Settings → Privacy & Security →
Microphone) — macOS asks on first run.
"""
from __future__ import annotations

import argparse
import sys
import wave
from pathlib import Path

import numpy as np

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

from bench.fixture import FIXTURES_DIR, Fixture  # noqa: E402

TARGET_RATE = 16000


def to_pcm16_16k(samples: np.ndarray, rate: int) -> bytes:
    """float32 mono in [-1, 1] at `rate` -> PCM16 bytes at 16kHz."""
    if rate != TARGET_RATE:
        import torch
        import torchaudio.functional as F

        samples = F.resample(torch.from_numpy(samples), rate, TARGET_RATE).numpy()
    return (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16).tobytes()


def write_wav(path: Path, pcm16: bytes) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(TARGET_RATE)
        wav.writeframes(pcm16)


def record_until_enter(device: int | None) -> tuple[np.ndarray, int]:
    import sounddevice as sd

    rate = int(sd.query_devices(device, "input")["default_samplerate"])
    chunks: list[np.ndarray] = []
    with sd.InputStream(samplerate=rate, channels=1, dtype="float32", device=device,
                        callback=lambda data, frames, t, status: chunks.append(data[:, 0].copy())):
        input("  ● recording… press Enter to stop ")
    return (np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)), rate


def play(path: Path) -> None:
    import sounddevice as sd

    with wave.open(str(path), "rb") as wav:
        audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
    sd.play(audio, TARGET_RATE)
    sd.wait()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("script", type=Path, nargs="?", help="bench/scripts/*.yaml")
    ap.add_argument("--out-dir", type=Path, help="default: bench/fixtures/<script name>")
    ap.add_argument("--device", type=int, help="input device index (see --list-devices)")
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--redo", type=int, nargs="*", default=[], help="turn numbers (1-based) to record again")
    args = ap.parse_args(argv)

    if args.list_devices:
        import sounddevice as sd

        print(sd.query_devices())
        return
    if args.script is None:
        ap.error("script is required")

    script = Fixture.from_script(args.script)
    out_dir = args.out_dir or FIXTURES_DIR / script.name
    existing = Fixture.load(out_dir) if (out_dir / "fixture.json").exists() else None
    fixture = script
    if existing is not None:
        # Keep recordings/transcripts of turns whose line hasn't changed.
        for turn, old in zip(fixture.turns, existing.turns):
            if old.user_script == turn.user_script:
                turn.audio, turn.user_stt = old.audio, old.user_stt
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Recording {script.name}: {len(script.turns)} turns -> {out_dir}")
    print("Speak naturally, the way you would in the app. Enter = start, Enter = stop.\n")
    for index, turn in enumerate(fixture.turns, start=1):
        if turn.audio and index not in args.redo:
            continue
        if index > 1:
            print(f"  ({fixture.turns[index - 2].assistant_reference})")
        print(f"[{index}/{len(fixture.turns)}] {turn.user_script}")
        while True:
            input("  press Enter to start ")
            samples, rate = record_until_enter(args.device)
            duration = len(samples) / rate if rate else 0.0
            peak = float(np.abs(samples).max()) if len(samples) else 0.0
            name = f"turn{index:02d}.wav"
            write_wav(out_dir / name, to_pcm16_16k(samples, rate))
            warn = "  ⚠ very quiet — check the input device" if peak < 0.05 else ""
            print(f"  saved {name}: {duration:.1f}s, peak {peak:.2f}{warn}")
            choice = input("  Enter = keep, p = play back, r = record again: ").strip().lower()
            while choice == "p":
                play(out_dir / name)
                choice = input("  Enter = keep, p = play back, r = record again: ").strip().lower()
            if choice != "r":
                break
        turn.audio, turn.user_stt = name, None  # new audio -> transcript is stale
        fixture.save(out_dir)  # after every turn, so stopping midway loses nothing
    fixture.save(out_dir)
    missing = [i for i, t in enumerate(fixture.turns, start=1) if not t.audio]
    print("done." if not missing else f"turns without audio: {missing}")
    print("Next: uv run python -m bench.transcribe", out_dir)


if __name__ == "__main__":
    main()
