"""Run one LLM backend through a benchmark conversation (Chronix AE-2).

Usage (from /server, with exactly one backend serving a model):

    uv run python -m bench.run bench/fixtures/smalltalk_b1 \\
        --backend ollama --model gemma2:27b --label ollama-gemma2-27b \\
        --process-pattern llama-server

    uv run python -m bench.run bench/fixtures/smalltalk_b1 \\
        --backend openai --model mlx-community/gemma-2-27b-it-4bit \\
        --base-url http://127.0.0.1:8080 --label mlx-gemma2-27b \\
        --process-pattern mlx_lm.server

Equal conditions, by construction:
- the system prompt is the production one (`compose_system_prompt`, the
  fixture's character and level, no memory);
- `--mode teacher` (default): after each turn the *reference* reply from
  the script goes into history, not the model's own, so every backend
  sees byte-identical prompts on every turn;
- greedy decoding, same `max_tokens`/`seed` (`GenParams`);
- each repeat starts with a random tag at the top of the system prompt,
  so its first turn can't reuse a cached prefix from an earlier repeat
  (that turn is reported as `cold`), while later turns exercise the same
  prefix reuse the live pipeline relies on;
- `--warmup` repeats run first and are discarded (model load, Metal
  shader compile).

`--mode free` keeps the model's own replies instead — prompts diverge
between backends, so use it for reading replies (quality), not timing.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
import secrets
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

from app.config import get_config  # noqa: E402
from app.persona import ENGLISH_LEVELS  # noqa: E402
from app.presets import PresetStore  # noqa: E402
from app.ws_session import compose_system_prompt  # noqa: E402
from bench.backends import Backend, GenParams, make_backend  # noqa: E402
from bench.fixture import BENCH_DIR, Fixture  # noqa: E402
from bench.memory import MemorySampler  # noqa: E402
from bench.metrics import TurnResult, measure_turn  # noqa: E402

RESULTS_DIR = BENCH_DIR / "results"


def system_prompt_for(fixture: Fixture) -> str:
    preset = PresetStore(get_config()).get(fixture.character_id)
    if preset is None:
        raise SystemExit(f"unknown character {fixture.character_id!r} in fixture {fixture.name!r}")
    if fixture.english_level not in ENGLISH_LEVELS:
        raise SystemExit(f"unknown english_level {fixture.english_level!r}")
    return compose_system_prompt(preset, None, fixture.english_level, None)


async def run_conversation(
    backend: Backend,
    fixture: Fixture,
    system_prompt: str,
    params: GenParams,
    mode: str,
    text_source: str,
    max_turns: int | None = None,
    sampler: MemorySampler | None = None,
    verbose: bool = True,
    prewarm_reply: bool = False,
) -> list[TurnResult]:
    messages = [{"role": "system", "content": f"[benchmark run {secrets.token_hex(4)}]\n{system_prompt}"}]
    results = []
    for index, turn in enumerate(fixture.turns[:max_turns]):
        messages.append({"role": "user", "content": turn.user_text(text_source)})
        if sampler is not None:
            sampler.window()
        try:
            result = await measure_turn(backend, messages, params, turn=index, cold=index == 0)
        except Exception as exc:  # keep going: one failed turn shouldn't lose the run
            result = TurnResult(turn=index, cold=index == 0, ttft_s=None, first_sentence_s=None,
                                total_s=0.0, chunks=0, reply="", error=f"{type(exc).__name__}: {exc}")
        if sampler is not None:
            result.peak_rss_mb = round(sampler.window().rss_mb, 1)
        reply = turn.assistant_reference if mode == "teacher" else result.reply
        messages.append({"role": "assistant", "content": reply})
        if prewarm_reply and index < len(fixture.turns[:max_turns]) - 1:
            # Live, this runs while TTS plays the reply; awaited here so it
            # never overlaps the next measured turn.
            started = time.perf_counter()
            await backend.prewarm(messages, params)
            result.prewarm_s = round(time.perf_counter() - started, 3)
        results.append(result)
        if verbose:
            print(_format_turn(result), flush=True)
    return results


def _format_turn(r: TurnResult) -> str:
    if r.error:
        return f"  turn {r.turn:>2}  ERROR {r.error}"
    def s(v):
        return "   -  " if v is None else f"{v:6.2f}"
    tag = "cold" if r.cold else "    "
    return (
        f"  turn {r.turn:>2} {tag}  ttft {s(r.ttft_s)}s  first_sentence {s(r.first_sentence_s)}s  "
        f"total {s(r.total_s)}s  decode {s(r.decode_tps)} tok/s  prefill {s(r.prefill_tps)} tok/s  "
        + (f"prewarm {r.prewarm_s:.2f}s  " if r.prewarm_s is not None else "")
        + f"| {r.reply.strip()[:60]!r}"
    )


def _machine() -> dict:
    def sysctl(name: str) -> str:
        return subprocess.run(["sysctl", "-n", name], capture_output=True, text=True).stdout.strip()
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                                cwd=SERVER_DIR).stdout.strip()
    except OSError:
        commit = ""
    return {
        "chip": sysctl("machdep.cpu.brand_string"),
        "memory_gb": round(int(sysctl("hw.memsize") or 0) / 2**30),
        "macos": platform.mac_ver()[0],
        "git_commit": commit,
    }


def inputs_digest(fixture: Fixture, system_prompt: str, text_source: str, turns: int | None) -> str:
    """Hash of everything fed to the model, so `compare` can catch runs
    whose transcripts or prompt changed in between (e.g. a re-recorded turn)."""
    parts = [system_prompt] + [f"{t.user_text(text_source)}\0{t.assistant_reference}" for t in fixture.turns[:turns]]
    return hashlib.sha256("\0\0".join(parts).encode()).hexdigest()[:16]


async def main(argv: list[str] | None = None) -> Path:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fixture", type=Path, help="fixture dir (recorded) or script YAML (text only)")
    ap.add_argument("--backend", required=True, choices=["ollama", "openai"])
    ap.add_argument("--model", required=True)
    ap.add_argument("--base-url")
    ap.add_argument("--fold-system", action="store_true",
                    help="openai backend: merge the system prompt into the first user turn, as Ollama's gemma2 "
                         "template does (needed for Gemma 2 on mlx_lm.server)")
    ap.add_argument("--label", required=True, help="name for this backend+model in reports")
    ap.add_argument("--mode", choices=["teacher", "free"], default="teacher")
    ap.add_argument("--text-source", choices=["stt", "script"],
                    help="user text: whisper transcript of the recording (default if present) or the script line")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--warmup", type=int, default=1)
    ap.add_argument("--turns", type=int, help="only the first N turns")
    ap.add_argument("--max-tokens", type=int, default=GenParams.max_tokens)
    ap.add_argument("--process-pattern", help="regex for the backend's process command line (memory sampling)")
    ap.add_argument("--baseline-system-mb", type=float,
                    help="system used memory before the backend started (`python -m bench.memory`)")
    ap.add_argument("--prewarm-reply", action="store_true",
                    help="after each reply, re-evaluate history + reply (num_predict 1) before the next turn, "
                         "as the live server could while TTS plays (Ollama backend)")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)

    fixture = Fixture.load(args.fixture)
    text_source = args.text_source or ("stt" if all(t.user_stt for t in fixture.turns) else "script")
    params = GenParams(max_tokens=args.max_tokens)
    system_prompt = system_prompt_for(fixture)
    backend = make_backend(args.backend, args.model, args.base_url, args.fold_system)
    print(f"{args.label}: {fixture.name} ({len(fixture.turns[:args.turns])} turns), mode={args.mode}, "
          f"text={text_source}, warmup={args.warmup}, repeats={args.repeats}")

    sampler = MemorySampler(args.process_pattern)
    sampler.start()
    runs = []
    try:
        for i in range(args.warmup):
            print(f"warmup {i + 1}/{args.warmup} (discarded)")
            await run_conversation(backend, fixture, system_prompt, params, args.mode, text_source,
                                   args.turns, verbose=False, prewarm_reply=args.prewarm_reply)
        sampler.overall = type(sampler.overall)()  # peaks from the measured repeats only
        for i in range(args.repeats):
            print(f"repeat {i + 1}/{args.repeats}")
            turns = await run_conversation(backend, fixture, system_prompt, params, args.mode, text_source,
                                           args.turns, sampler=sampler, prewarm_reply=args.prewarm_reply)
            runs.append({"repeat": i, "turns": [asdict(t) for t in turns]})
    finally:
        await sampler.stop()
        await backend.aclose()

    report = {
        "label": args.label,
        "backend": {"kind": args.backend, "model": args.model, "base_url": args.base_url,
                    "fold_system": args.fold_system, "prewarm_reply": args.prewarm_reply},
        "fixture": fixture.name,
        "mode": args.mode,
        "text_source": text_source,
        "inputs_sha256": inputs_digest(fixture, system_prompt, text_source, args.turns),
        "params": asdict(params),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "machine": _machine(),
        "memory": {
            "baseline_system_mb": args.baseline_system_mb,
            "peak_system_mb": round(sampler.overall.system_mb),
            "peak_system_delta_mb": (
                round(sampler.overall.system_mb - args.baseline_system_mb) if args.baseline_system_mb else None
            ),
            "peak_rss_mb": round(sampler.overall.rss_mb),
            "process_pattern": args.process_pattern,
        },
        "runs": runs,
    }
    out = args.out or RESULTS_DIR / f"{args.label}-{fixture.name}-{args.mode}-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"saved {out}")
    return out


if __name__ == "__main__":
    asyncio.run(main())
