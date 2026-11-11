"""Word error rate of whisper models on recorded fixtures, with and without
a context prompt (the character's previous line).

    uv run python -m bench.stt_eval bench/fixtures/smalltalk_b1 bench/fixtures/interview_coach_b1 \\
        --model poc/whisper.cpp/models/ggml-medium.en.bin --model poc/whisper.cpp/models/ggml-large-v3-turbo.bin

Reference = the script line the developer read, so a paraphrase counts as
an error too. Every variant pays that equally, which makes the comparison
fair, but the absolute WER is a bit pessimistic. Runs its own
whisper-server on `--port` (default 8791), so the live server on 8781
keeps working. Don't use the app while this runs, because both share the GPU.
"""
from __future__ import annotations

import argparse
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

import httpx
import numpy as np

SERVER_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = SERVER_DIR.parent
sys.path.insert(0, str(SERVER_DIR))

from app.ws_session import NON_SPEECH_MARKER  # noqa: E402
from bench.fixture import Fixture  # noqa: E402

WHISPER_BIN = REPO_DIR / "poc/whisper.cpp/build/bin/whisper-server"
NUMBERS = {str(i): w for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty".split())}


def normalize(text: str) -> list[str]:
    text = text.lower().replace("’", "'")
    words = re.sub(r"[^a-z0-9' ]+", " ", text).split()
    return [NUMBERS.get(w, w) for w in (w.strip("'") for w in words) if w]


def word_errors(ref: list[str], hyp: list[str]) -> int:
    """Levenshtein distance over words (substitutions + insertions + deletions)."""
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h)))
        prev = cur
    return prev[-1]


def peak_normalize(wav: bytes, peak: float = 0.9) -> bytes:
    """Scale a PCM16 WAV so its loudest sample sits at `peak` of full scale."""
    header, pcm = wav[:44], np.frombuffer(wav[44:], dtype=np.int16).astype(np.float32)
    top = float(np.abs(pcm).max()) if len(pcm) else 0.0
    if top == 0:
        return wav
    return header + np.clip(pcm * (peak * 32767 / top), -32768, 32767).astype(np.int16).tobytes()


def start_server(model: Path, port: int) -> subprocess.Popen:
    proc = subprocess.Popen([str(WHISPER_BIN), "-m", str(model), "--host", "127.0.0.1", "--port", str(port), "-nt"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"whisper-server exited early for {model}")
        try:
            if httpx.get(f"http://127.0.0.1:{port}/", timeout=1).status_code < 500:
                return proc
        except httpx.TransportError:
            time.sleep(0.5)
    proc.kill()
    raise SystemExit("whisper-server did not start")


def transcribe(client: httpx.Client, wav: bytes, prompt: str | None) -> tuple[str, float]:
    data = {"temperature": "0.0", "response_format": "text"}
    if prompt:
        data["prompt"] = prompt
    started = time.perf_counter()
    resp = client.post("/inference", files={"file": ("a.wav", wav, "audio/wav")}, data=data)
    resp.raise_for_status()
    return NON_SPEECH_MARKER.sub("", resp.text).strip(), time.perf_counter() - started


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fixtures", type=Path, nargs="+")
    ap.add_argument("--model", type=Path, action="append", required=True, help="ggml model (repeatable)")
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--show", action="store_true", help="print every transcript that isn't an exact match")
    ap.add_argument("--normalize", action="store_true", help="also test peak-normalized audio")
    ap.add_argument("--prompt", choices=["both", "yes", "no"], default="both")
    args = ap.parse_args(argv)

    clips = []  # (label, wav bytes, reference, prompt)
    for path in args.fixtures:
        fixture = Fixture.load(path)
        for i, turn in enumerate(fixture.turns):
            if turn.audio:
                prompt = fixture.turns[i - 1].assistant_reference if i > 0 else None
                clips.append((f"{fixture.name}#{i + 1}", (fixture.dir / turn.audio).read_bytes(),
                              turn.user_script, prompt))

    rows = []
    for model in args.model:
        model = model if model.is_absolute() else (REPO_DIR / model if not model.exists() else model)
        proc = start_server(model, args.port)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{args.port}", timeout=60) as client:
                transcribe(client, clips[0][1], None)  # warmup (Core ML / Metal compile)
                prompts = {"both": (False, True), "yes": (True,), "no": (False,)}[args.prompt]
                variants = [(p, False) for p in prompts] + ([(p, True) for p in prompts] if args.normalize else [])
                for use_prompt, normalized in variants:
                    errors = ref_words = 0
                    latencies = []
                    for label, wav, ref, prompt in clips:
                        text, seconds = transcribe(client, peak_normalize(wav) if normalized else wav,
                                                   prompt if use_prompt else None)
                        latencies.append(seconds)
                        e = word_errors(normalize(ref), normalize(text))
                        errors += e
                        ref_words += len(normalize(ref))
                        if args.show and e:
                            print(f"  [{model.stem} prompt={use_prompt}] {label} ({e}): {text}")
                    rows.append((model.stem + (" +norm" if normalized else ""), use_prompt, errors / ref_words * 100,
                                 statistics.median(latencies), max(latencies)))
        finally:
            proc.terminate()
            proc.wait(timeout=10)

    print(f"\n{len(clips)} clips\n")
    print("| model | context prompt | WER | median latency | max latency |")
    print("|---|---|---|---|---|")
    for name, use_prompt, wer, med, worst in rows:
        print(f"| {name} | {'yes' if use_prompt else 'no'} | {wer:.1f}% | {med:.2f}s | {worst:.2f}s |")


if __name__ == "__main__":
    main()
