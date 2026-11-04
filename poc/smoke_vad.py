"""Smoke test: silero-vad detects speech segments in a trivial known sample."""
import sys
import numpy as np
import soundfile as sf
import torch
from silero_vad import load_silero_vad, get_speech_timestamps

AUDIO = "samples/test_input.wav"

def main():
    model = load_silero_vad()
    data, sr = sf.read(AUDIO, dtype="float32")
    assert sr == 16000, f"expected 16kHz, got {sr}"
    wav = torch.from_numpy(data)
    timestamps = get_speech_timestamps(wav, model, sampling_rate=16000, return_seconds=True)
    print(f"speech segments: {timestamps}")
    ok = len(timestamps) > 0
    print("PASS" if ok else "FAIL")
    if not ok:
        sys.exit(1)

if __name__ == "__main__":
    main()
