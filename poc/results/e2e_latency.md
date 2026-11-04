---
story: STORY-01-05
status: complete
updated: 2026-09-03
---

# STORY-01-05 — End-to-end CLI pipeline & true TTFA measurement: results

## Pipeline built (`poc/e2e_pipeline.py`)

Recorded clip (VAD-trimmed to detected speech end) → **STT**
(`whisper.cpp` + Core ML, `medium.en`, per `stt_engine_spike.md`) →
**LLM** (`qwen2.5:32b` via Ollama, streamed, per `llm_benchmark.md`) →
**TTS** (Piper `en_US-lessac-medium`, first sentence only, per
`tts_benchmark.md`) → **playback** (`afplay`).

**TTFA definition used**: wall-clock time from VAD-detected end of user
speech to the moment the first response-audio chunk starts playing (i.e.
gated by the *first sentence* only, consistent with the chunked-streaming
design validated in `STORY-01-04` — not the full response).

**Methodology note — reused recordings, not 10 fresh live turns**:
by agreement with Andrey, this run reuses the 5 real-voice clips from
`STORY-01-02` (2 passes each = 10 turns) rather than 10 new live mic
recordings. VAD still runs on each clip to find the real speech-end
boundary (trimming trailing silence), so the STT→LLM→TTS→playback chain
being measured is identical to what a live VAD trigger would feed it —
only the "record from a live mic" step itself is skipped. LLM responses
vary turn to turn (not deterministic/cached), so this isn't 5 unique
data points ×2 — it's 10 independent full pipeline runs.

"Warm" condition: LLM warmed with one throwaway call before timing
started (Ollama keeps it resident). STT and TTS still pay their
per-process load cost every call, since both run as fresh subprocesses
(`whisper-cli`, `piper`) rather than persistent servers — see finding
below on why this matters more than expected.

## TTFA distribution (10 turns)

| Stat | Value |
|---|---|
| Median | **6.37s** |
| p90 | **7.84s** |
| Min | 5.39s |
| Max | 8.36s |

**Does this meet the PRD's ≤1.5s TTFA budget? No — by a wide margin.**
Median is **~4.2x over budget**, worst case **~5.6x over**.

## Per-stage breakdown (mean across 10 turns)

| Stage | Mean latency | Share of TTFA |
|---|---|---|
| STT (whisper.cpp+CoreML) | 2.55s | 39% |
| LLM time-to-first-sentence | 1.01s | 16% |
| TTS (Piper, first sentence) | 2.95s | 45% |

No single stage dominates — **all three contribute meaningfully**, unlike
earlier component-level benchmarks which suggested TTS (Piper, ~0.6s)
and STT (whisper.cpp, ~1.6s isolated) were each individually closer to
negligible.

## ⚠️ Finding: component-level benchmarks were measured on a "quiet" system; this pipeline ran on a system with accumulated load from the whole session

Both STT and TTS latency are markedly higher here than their isolated
STORY-01-02/01-04/`stt_engine_spike` numbers:
- STT: 2.55s avg here vs. **1.56s** isolated (`stt_engine_spike.md`)
- TTS: 2.95s avg here vs. **0.59s** isolated (`tts_benchmark.md`) — a
  ~5x jump

Investigated directly: re-running the exact same Piper subprocess
command standalone from a fresh shell reproduced the original ~0.6s —
so this is **not** a code bug in the pipeline (e.g. not `uv run`
subprocess-nesting overhead, which was the first suspicion and was
ruled out by a direct A/B timing test). Memory checks during the 10-turn
run showed low free pages and continued swap growth — consistent with
this being a **memory-pressure effect from cumulative session activity**
(many multi-GB models loaded/unloaded across `STORY-01-01` through
`STORY-01-04`, plus this session's own Xcode install and whisper.cpp
build), not a one-off fluke.

**This is arguably the most important finding of this story**: an
isolated "fresh system" component benchmark can be **meaningfully
optimistic** compared to sustained real-world operation, where memory
pressure accumulates over a long-running server process. The real server
(EPIC-02+) needs either (a) enough headroom that this doesn't recur in
practice, or (b) its own monitoring/alerting on memory pressure, not an
assumption that component-level PoC numbers hold indefinitely.

## Bottleneck analysis

Under this (pressured) system state, **no single stage is "the"
bottleneck** — STT, LLM, and TTS are all in the same 1-3s range. Under a
quieter system (extrapolating from isolated benchmarks: ~1.6s STT + ~1s
LLM + ~0.6s TTS ≈ **3.2s**), the picture would still be **~2.1x over
budget**, with STT and LLM roughly tied as the largest contributors and
TTS a smaller share.

Either way — pressured or quiet — **the ≤1.5s PRD budget is not met**.

## Recommendation

- **The PRD's ≤1.5s TTFA budget needs an ADR revising it.** Even under
  favorable (quiet-system, extrapolated) conditions this pipeline lands
  around 3.2s; under realistic sustained-session conditions, 6.4s median.
  This is the load-bearing evidence STORY-01-02's and the STT-engine
  spike's open questions were waiting on.
- **Before finalizing that ADR's proposed number, STT streaming decode
  is still untested** (`whisper.cpp examples/stream`) and could
  meaningfully lower the STT contribution — recommend a quick follow-up
  spike on that specifically, since it's the one variable in this
  breakdown not yet explored, before locking in a revised budget number.
- **Investigate running STT/TTS as persistent servers instead of
  per-turn subprocesses** for the real implementation (`whisper-server`
  ships with `whisper.cpp`; Piper can be wrapped similarly) — this
  PoC's per-call process spawn/model-load cost is avoidable in a real
  server and is inflating these numbers beyond what a proper
  long-running service would show.
- **Memory-pressure sensitivity is now confirmed as a first-class
  concern for EPIC-02+ server design**, not just a PoC-environment
  artifact — consistent with the `llama3.3:70b` incident and the
  `large-v3` cold-load stall from earlier stories. Budget real headroom,
  not just "does it fit right now."
