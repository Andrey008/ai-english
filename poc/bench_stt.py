"""STORY-01-02: STT latency & accuracy benchmark on real speech samples.
Measures per-clip transcription latency for medium.en and large-v3,
isolated (no other load) and under resource contention (LLM + TTS warm).
"""
import glob
import json
import sys
import time
from faster_whisper import WhisperModel

CLIPS = sorted(glob.glob("samples/real_voice/clip*.wav"))

def bench(model_size: str, tag: str):
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    results = []
    for clip in CLIPS:
        t0 = time.time()
        segments, info = model.transcribe(clip, language="en")
        text = " ".join(s.text for s in segments).strip()
        dt = time.time() - t0
        results.append({"clip": clip, "latency_s": round(dt, 3), "text": text})
        print(f"[{tag}] {model_size} {clip}: {dt:.3f}s -> {text!r}")
    return results

if __name__ == "__main__":
    tag = sys.argv[1] if len(sys.argv) > 1 else "isolated"
    out = {}
    for m in ["medium.en", "large-v3"]:
        out[m] = bench(m, tag)
    with open(f"results/stt_bench_{tag}.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nWritten to results/stt_bench_{tag}.json")
