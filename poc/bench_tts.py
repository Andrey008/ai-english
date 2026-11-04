"""STORY-01-04: TTS latency & voice quality benchmark.
Measures per-chunk (sentence-level, simulating streaming) synthesis
latency for Piper (3 voices) and XTTS v2 (stock speaker + cloned voice).
"""
import json
import os
import sys
import time

os.environ.setdefault("COQUI_TOS_AGREED", "1")

CHUNKS = [
    "That sounds like a really frustrating situation with your neighbor.",
    "Have you thought about what you'd actually say to him?",
    "I think staying calm is going to matter more than being right.",
    "Let's practice how you might start that conversation.",
]

OUT_DIR = "results/tts_samples"
os.makedirs(OUT_DIR, exist_ok=True)


def bench_piper():
    import subprocess
    voices = ["en_US-lessac-medium", "en_GB-alan-medium", "en_US-amy-medium"]
    results = {}
    for v in voices:
        results[v] = []
        for i, chunk in enumerate(CHUNKS):
            out = f"{OUT_DIR}/piper_{v}_chunk{i}.wav"
            t0 = time.time()
            subprocess.run(
                ["uv", "run", "python", "-m", "piper",
                 "-m", f"voices/{v}.onnx", "-c", f"voices/{v}.onnx.json",
                 "-f", out],
                input=chunk, text=True, capture_output=True, check=True,
            )
            dt = time.time() - t0
            results[v].append({"chunk": i, "latency_s": round(dt, 3), "text": chunk})
            print(f"[piper/{v}] chunk{i}: {dt:.3f}s")
    return results


def bench_xtts():
    from TTS.api import TTS
    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2")

    results = {"stock_claribel": [], "cloned_from_test_input": []}

    for i, chunk in enumerate(CHUNKS):
        out = f"{OUT_DIR}/xtts_stock_chunk{i}.wav"
        t0 = time.time()
        tts.tts_to_file(text=chunk, speaker="Claribel Dervla", language="en", file_path=out)
        dt = time.time() - t0
        results["stock_claribel"].append({"chunk": i, "latency_s": round(dt, 3), "text": chunk})
        print(f"[xtts/stock] chunk{i}: {dt:.3f}s")

    for i, chunk in enumerate(CHUNKS):
        out = f"{OUT_DIR}/xtts_cloned_chunk{i}.wav"
        t0 = time.time()
        tts.tts_to_file(text=chunk, speaker_wav="samples/test_input.wav", language="en", file_path=out)
        dt = time.time() - t0
        results["cloned_from_test_input"].append({"chunk": i, "latency_s": round(dt, 3), "text": chunk})
        print(f"[xtts/cloned] chunk{i}: {dt:.3f}s")

    return results


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    out = {}
    if which in ("all", "piper"):
        out["piper"] = bench_piper()
    if which in ("all", "xtts"):
        out["xtts"] = bench_xtts()
    with open("results/tts_bench.json", "w") as f:
        json.dump(out, f, indent=2)
    print("\nWritten to results/tts_bench.json")
