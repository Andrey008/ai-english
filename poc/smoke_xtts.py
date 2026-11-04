"""Smoke test: XTTS v2 voice cloning produces a non-trivial audio file from a
short reference sample. Quality is assessed later in STORY-01-04 — this just
confirms the pipeline runs end to end."""
import os
import sys
import time

os.environ.setdefault("COQUI_TOS_AGREED", "1")

from TTS.api import TTS

REFERENCE = "samples/test_input.wav"
OUTPUT = "samples/xtts_clone_test.wav"
TEXT = "This is a cloned voice speaking a proof of concept test sentence."

def main():
    t0 = time.time()
    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2")
    load_s = time.time() - t0

    t0 = time.time()
    tts.tts_to_file(text=TEXT, speaker_wav=REFERENCE, language="en", file_path=OUTPUT)
    infer_s = time.time() - t0

    ok = os.path.exists(OUTPUT) and os.path.getsize(OUTPUT) > 10_000
    print(f"load: {load_s:.2f}s  infer: {infer_s:.2f}s  size: {os.path.getsize(OUTPUT) if ok else 0} bytes")
    print("PASS" if ok else "FAIL")
    if not ok:
        sys.exit(1)

if __name__ == "__main__":
    main()
