"""STORY-01-03: LLM latency benchmark on real Ollama-hosted candidates.
Measures first-token latency and tokens/sec (streaming) per model, plus a
memory/processor snapshot via `ollama ps` while the model is loaded and
generating. Run with an optional tag (isolated/contention) to match the
STORY-01-02 convention -- for "contention", run contention_load.py in the
background first (loads medium.en STT + loops Piper synthesis).
"""
import json
import subprocess
import sys
import time

import ollama

MODELS = ["qwen2.5:32b", "gemma2:27b"]

# A few varied-length prompts so tokens/sec isn't a single-sample fluke.
PROMPTS = [
    "In one short sentence, what's a good way to practice spoken English daily?",
    "Explain, in 3-4 sentences, why small talk is hard for non-native speakers "
    "and give one concrete tip to get better at it.",
    "Tell me a short (5-6 sentence) story about a neighbor complaining about "
    "noise, written in a casual conversational tone.",
]


def ollama_ps_snapshot() -> str:
    try:
        out = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=10)
        return out.stdout.strip()
    except Exception as e:  # pragma: no cover - diagnostic only
        return f"<ollama ps failed: {e}>"


def bench_one(model: str, prompt: str) -> dict:
    t0 = time.time()
    first_token_t = None
    chunks = []
    stream = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        stream=True,
    )
    for chunk in stream:
        if first_token_t is None:
            first_token_t = time.time()
        piece = chunk.get("message", {}).get("content", "")
        if piece:
            chunks.append(piece)
    t_end = time.time()

    text = "".join(chunks)
    # Rough token count (whitespace split) -- good enough for a tok/s estimate.
    n_tokens = max(len(text.split()), 1)
    gen_s = t_end - (first_token_t or t_end)
    return {
        "prompt": prompt,
        "first_token_latency_s": round((first_token_t or t_end) - t0, 3),
        "total_latency_s": round(t_end - t0, 3),
        "gen_only_s": round(gen_s, 3),
        "approx_tokens": n_tokens,
        "approx_tokens_per_s": round(n_tokens / gen_s, 2) if gen_s > 0 else None,
        "reply_preview": text[:200],
    }


def bench_model(model: str) -> dict:
    print(f"\n=== {model} ===")
    # Warm-up call: excludes cold model-load time from the per-prompt numbers
    # below (STORY-01-01/02 already showed cold-load can dominate and isn't
    # representative of steady-state turn latency).
    t0 = time.time()
    ollama.chat(model=model, messages=[{"role": "user", "content": "Say hi."}])
    warmup_s = time.time() - t0
    print(f"warmup (cold load): {warmup_s:.2f}s")

    runs = []
    for p in PROMPTS:
        r = bench_one(model, p)
        print(
            f"  first_token={r['first_token_latency_s']}s  "
            f"total={r['total_latency_s']}s  ~{r['approx_tokens_per_s']} tok/s"
        )
        runs.append(r)

    ps_snapshot = ollama_ps_snapshot()
    print(f"  ollama ps:\n{ps_snapshot}")

    return {"model": model, "warmup_s": round(warmup_s, 2), "runs": runs, "ollama_ps": ps_snapshot}


if __name__ == "__main__":
    tag = sys.argv[1] if len(sys.argv) > 1 else "isolated"
    results = [bench_model(m) for m in MODELS]
    out_path = f"results/llm_bench_{tag}.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nWritten to {out_path}")
