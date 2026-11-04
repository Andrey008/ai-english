---
epic: EPIC-01
title: PoC findings report & decision log
status: Phase 1 complete
updated: 2026-09-03
---

# EPIC-01 PoC — Findings report

Consolidated output of all 8 Phase-1 stories. This is the "start here"
document for Phase 2 planning — it names every decision and the config
values that go with it; the individual `poc/results/*.md` files have
the full measurement detail and methodology behind each one.

## Chosen components

| Component | Choice | Why |
|---|---|---|
| **STT engine** | `whisper.cpp` + Core ML, **streaming mode** (`whisper-stream`, sliding-window VAD) | `faster-whisper`/`ctranslate2` has no Apple Silicon GPU/ANE backend (6.51s avg). Switching engine (same `medium.en` model) to `whisper.cpp`+CoreML batch mode: 1.56s. Streaming mode: **540ms median** — the number to build against. See `stt_engine_spike.md`. |
| **STT model** | `medium.en` | Comparable accuracy to `large-v3` on Andrey's real (non-native-accented) speech, meaningfully faster. See `stt_benchmark.md`. |
| **LLM (primary/conversational)** | `qwen2.5:32b` via Ollama | Fast (GPU-accelerated, ~100% GPU utilization), stayed in-character where `gemma2:27b` broke persona once ("as a language model..."). See `llm_benchmark.md`. |
| **LLM (learning-layer candidate)** | `gemma2:27b` reserved | Not used for the live conversational path, but fine for a non-critical-path learning-layer pass (EPIC-04) if needed later. |
| **LLM (rejected)** | `llama3.3:70b` — **dropped entirely** | Caused an OS-level OOM kill and system-wide memory pressure on this 48GB machine; 290s for a one-word reply even when it did complete. Removed from Ollama. See `setup.md`. |
| **TTS engine (default)** | Piper (`en_US-lessac-medium`, or any of the 3 voices tested — near-identical latency) | ~0.59s/chunk, vs. XTTS v2's 1.56s (stock)/2.17s (cloned). Andrey's live A/B listen rated Piper as not clearly worse — sometimes preferred — despite the large latency gap. See `tts_benchmark.md`. |
| **TTS engine (optional mode)** | XTTS v2, stock speakers only | Kept as a non-default option for character-voice variety where the latency is acceptable outside the tightest real-time path. |
| **Voice cloning** | **Deferred, not shipping now** | Slowest option tested, and the only one with audible artifacts Andrey confirmed directly. Revisit only on a specific concrete need. |
| **VAD** | Silero VAD (`VADIterator` for streaming barge-in use) | Fast (~360ms cold, near-instant warm), zero false positives on non-speech noise in testing. |

## Latency budget: revised (ADR-0006)

Original ≤1.5s TTFA / ≤250ms VAD+STT (from the pre-PoC spec) is **not
reachable** on this hardware running the full pipeline locally. Revised,
evidence-based working target:

| Stage | Quiet/best-case | Sustained-session realistic |
|---|---|---|
| VAD + STT (streaming) | ~550ms | ~1.0-2.5s (untested under contention — see Follow-ups) |
| LLM time-to-first-sentence | ~1.1s | ~1.1-1.7s |
| TTS first chunk (Piper) | ~0.6s | ~2-3s |
| Network overhead | untested (Mac-only PoC) | untested |
| **Total TTFA** | **~2.3-2.5s** | **~4.6-6.4s** |

**Working target: ≤3s TTFA under quiet/normal conditions.** Full
rationale, the "why this isn't a workaround" argument, and concrete
EPIC-02 follow-ups (persistent STT/TTS servers being the highest-leverage
one) are in `Docs/decisions/ADR-0006-latency-budget-revision.md`.
`Docs/PRD.md` §7.1 and `Docs/ARCHITECTURE.md` §2.1 already updated to
match.

## Barge-in: GO (ADR-0004, now Accepted)

Resource-feasible with the chosen components: **median stop latency
24ms** (13 real interrupt events), **142s of sustained concurrent
LLM+TTS+VAD load with zero new swap activity**, zero false positives on
non-speech noise. Meaningfully lighter resource profile than the
NVIDIA-class real-time models Andrey was worried about matching.

One caveat, not blocking the GO: nearby-*human*-speech false-positive
risk (e.g. outdoor/park use) is untestable on this Mac PoC and needs a
real-environment field test once the Android client exists (EPIC-06).
Full detail: `bargein_feasibility.md`.

## Proactive persona: validated, baseline template ready for EPIC-03

`qwen2.5:32b` with a structured system-prompt template (personality/role
+ explicit anti-dead-end-fallback contract + `correction_style` slot)
sustained proactive behavior across 3 personalities × 18 turns each and
a 12-turn structured interview scenario, under deliberately passive
scripted user input — **71/72 turns proactive, zero regression**. No
mitigation needed. Baseline template is in `persona_findings.md`, ready
to carry into EPIC-03's character-preset system. Correction-style
variants (`live_gentle`, `end_of_session`) weren't tested — flagged for
EPIC-04 planning.

## Compute backend reality check

- **LLM**: confirmed GPU (Metal) via Ollama, ~100% GPU utilization.
- **STT encoder**: Core ML (`MLComputeUnitsAll`), very likely using the
  ANE given the ~1.5s-vs-5-10s speedup over CPU-only and GPU staying
  mostly idle during continuous inference — but **not empirically
  confirmed** (this machine's `powermetrics` doesn't expose an ANE power
  rail). Don't restate as settled fact; a better verification method
  (Xcode Instruments) wasn't attempted.
- **Both TTS engines currently run CPU-only**, despite unused
  acceleration paths existing (Piper's `onnxruntime` never tries
  `CoreMLExecutionProvider`; XTTS/PyTorch would need explicit
  `.to("mps")`). Not pursued — Piper is fast enough already and XTTS's
  quality didn't clearly justify the investment. Revisit only if a
  future story specifically needs XTTS performance.

## Incidents and the practices they produced

Two memory-pressure incidents shaped how the rest of Phase 1 was run,
and both are directly relevant to EPIC-02's server design:

1. **`llama3.3:70b` OOM** (`STORY-01-01`) — took down other running
   apps, cost Andrey real time (missed a daily standup). Root cause:
   a 42GB model on a 48GB machine leaves no headroom.
2. **`large-v3` cold-load stall** (`STORY-01-02`, 539s) — cold-loading
   any large model while another is already resident is the danger
   zone, independent of whether the combined footprint technically
   fits.

**Practice that came out of this and held up for the rest of Phase 1**:
check memory before/during any multi-model concurrent test, stick to
models already proven stable, never cold-load a second large model
while one is resident. `STORY-01-05`'s and `STORY-01-07`'s later
concurrent-load tests (with `qwen2.5:32b` + lightweight STT/TTS/VAD)
ran clean — zero new swap in both, confirming the pattern was specific
to oversized/newly-loading models, not concurrency itself.

## Open items carried into Phase 2 (not resolved here, by design)

1. **Persistent STT/TTS server processes** instead of per-call
   subprocess spawn — `STORY-01-05` found real, measured latency cost
   from process/model-load overhead per call. Highest-leverage item for
   closing the gap between "quiet" and "sustained-session" budget
   numbers. (ADR-0006 follow-up #1)
2. **Streaming STT under contention** — the 540ms streaming number is
   from an isolated test; batch-mode contention numbers don't transfer
   directly. Worth a quick check early in EPIC-02.
3. **Network overhead (Tailscale, Android↔Mac)** — completely
   unverified; first real client integration should measure it.
4. **Explicit server-side LLM-generation cancellation on interrupt** —
   the barge-in spike stopped client-side consumption but didn't
   confirm Ollama stops generating server-side. Real implementation
   needs this.
5. **Nearby-human-speech false-positive field test** for barge-in,
   once the Android client exists (EPIC-06).
6. **Correction-style behavior** (`live_gentle`/`end_of_session`) for
   the learning layer — untested, flagged for EPIC-04 planning.

## Where the raw evidence lives

`poc/results/`: `setup.md`, `stt_benchmark.md`, `stt_engine_spike.md`
(+ streaming addendum), `llm_benchmark.md`, `tts_benchmark.md`,
`e2e_latency.md`, `persona_findings.md`, `bargein_feasibility.md`. All
scripts that produced them are in `poc/` (gitignored per the project's
own `.gitignore` policy — this is throwaway PoC code, not shipped
product code, though kept around for reference per `EPIC-01`'s own
scope note).
