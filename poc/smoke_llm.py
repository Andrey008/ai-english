"""Smoke test: Ollama client can load a model and produce a coherent reply.
Model is passed as argv[1] so this can be re-run against each PoC candidate
once its `ollama pull` finishes."""
import sys
import time
import ollama

def main(model: str):
    t0 = time.time()
    resp = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": "Reply with exactly the word: PONG"}],
    )
    dt = time.time() - t0
    text = resp["message"]["content"].strip()
    print(f"model: {model}  time: {dt:.2f}s")
    print(f"reply: {text!r}")
    ok = "pong" in text.lower()
    print("PASS" if ok else "FAIL")
    if not ok:
        sys.exit(1)

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "qwen3.8:27b")
