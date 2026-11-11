"""Summarize per-turn latency from a server log (JSON lines).

    uv run python scripts/turn_timing_report.py story0511_run11.log [--session ID]

Per session:
- `ws_turn_timing` medians and p90. Every value is measured from VAD
  speech_end; the LLM share is first sentence minus STT.
- Reply-prewarm and compaction events, to confirm the background cache
  work ran and never got in the way (ADR-0012, ADR-0013).
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

EVENTS = ("llm_reply_prewarm_done", "llm_reply_prewarm_cancelled", "llm_reply_prewarm_failed",
          "llm_prewarm_done", "llm_compaction_deferred")


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", type=Path)
    ap.add_argument("--session", help="only this session id (prefix ok)")
    args = ap.parse_args()

    turns: dict[str, list[dict]] = defaultdict(list)
    events: dict[str, Counter] = defaultdict(Counter)
    prewarm_s: dict[str, list[float]] = defaultdict(list)
    for line in args.log.read_text().splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        sid = rec.get("session_id", "?")
        if args.session and not sid.startswith(args.session):
            continue
        msg = rec.get("message", "")
        if msg == "ws_turn_timing":
            turns[sid].append(rec)
        elif msg in EVENTS or msg.startswith("llm_compaction"):
            events[sid][msg] += 1
            if msg == "llm_reply_prewarm_done" and rec.get("duration_s") is not None:
                prewarm_s[sid].append(rec["duration_s"])

    for sid in sorted(set(turns) | set(events), key=lambda s: turns[s][0]["ts"] if turns[s] else ""):
        rows = turns[sid]
        start = rows[0]["ts"] if rows else "?"
        print(f"\n## session {sid[:8]}  started {start} UTC  turns {len(rows)}")
        later = rows[1:]  # first turn rides on the session-start prewarm, report it apart
        if rows:
            first = rows[0]
            print(f"  first turn:  first audio {first.get('first_audio_s')}s  "
                  f"llm {_llm(first)}s")
        for name, getter in (("first audio", lambda r: r.get("first_audio_s")),
                             ("llm 1st sentence", _llm),
                             ("stt", lambda r: r.get("stt_s"))):
            values = [v for v in (getter(r) for r in later) if v is not None]
            if values:
                print(f"  later turns {name:17} median {statistics.median(values):.2f}s  "
                      f"p90 {pct(values, 0.9):.2f}s  max {max(values):.2f}s  (n={len(values)})")
        if events[sid]:
            print("  events: " + ", ".join(f"{k}={v}" for k, v in sorted(events[sid].items())))
        if prewarm_s[sid]:
            print(f"  reply prewarm duration median {statistics.median(prewarm_s[sid]):.2f}s  "
                  f"max {max(prewarm_s[sid]):.2f}s")


def _llm(rec: dict) -> float | None:
    first, stt = rec.get("llm_first_sentence_s"), rec.get("stt_s")
    return None if first is None or stt is None else round(first - stt, 3)


if __name__ == "__main__":
    main()
