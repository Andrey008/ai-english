"""Smoke test: faster-whisper transcribes a trivial known-text sample."""
import sys
import time
from faster_whisper import WhisperModel

AUDIO = "samples/test_input.wav"
EXPECTED_SUBSTRING = "test sentence"

def run(model_size: str):
    print(f"\n=== {model_size} ===")
    t0 = time.time()
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    load_s = time.time() - t0

    t0 = time.time()
    segments, info = model.transcribe(AUDIO, language="en")
    text = " ".join(seg.text for seg in segments).strip()
    infer_s = time.time() - t0

    print(f"load: {load_s:.2f}s  infer: {infer_s:.2f}s")
    print(f"transcript: {text!r}")
    ok = EXPECTED_SUBSTRING in text.lower()
    print("PASS" if ok else "FAIL")
    return ok

if __name__ == "__main__":
    models = sys.argv[1:] or ["medium.en", "large-v3"]
    results = {m: run(m) for m in models}
    if not all(results.values()):
        sys.exit(1)
