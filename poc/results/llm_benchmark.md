---
story: STORY-01-03
status: complete
updated: 2026-09-03
---

# STORY-01-03 — LLM latency & quality benchmark: results

## Candidates

Only `qwen2.5:32b` and `gemma2:27b` — `llama3.3:70b` was dropped during
`STORY-01-01` after an OOM/system-wide memory-pressure incident (see
`/poc/results/setup.md`).

## ⚠️ Finding 0: unlike STT (`faster-whisper`/`ctranslate2`), Ollama LLM
inference **does use the M4 Pro's GPU**

`ollama ps` showed **100% GPU** for both candidates during every run (see
below) — Ollama's `llama.cpp`-based backend has a working Metal path on
Apple Silicon, which `ctranslate2` (used by `faster-whisper` for STT)
does not. This is good news for the pipeline's compute budget generally,
though it doesn't change the STT-specific gap flagged in
`stt_benchmark.md` (that bottleneck is specific to `ctranslate2`, not a
general "no GPU on this Mac" problem — reinforces the STORY-01-05 plan to
try GPU/ANE-capable STT engines before revising the PRD budget).

## Latency — isolated (LLM only, nothing else loaded)

3 prompts of increasing length/complexity (short factual, medium
explanatory, longer narrative). Full data: `results/llm_bench_isolated.json`.

| Model | cold-load (warmup) | avg first-token | avg total (per prompt) | avg tok/s |
|---|---|---|---|---|
| `qwen2.5:32b` | 10.26s | 0.48s | 6.77s | 9.76 |
| `gemma2:27b` | 7.55s | 0.65s | 6.55s | 10.35 |

Per-prompt breakdown (short / medium / long):

| Model | first-token (s) | total (s) | tok/s |
|---|---|---|---|
| `qwen2.5:32b` | 0.37 / 0.69 / 0.39 | 2.23 / 9.46 / 8.61 | 10.8 / 9.35 / 9.12 |
| `gemma2:27b` | 0.65 / 0.78 / 0.53 | 2.07 / 7.61 / 10.00 | 9.83 / 10.98 / 10.24 |

## Latency — under resource contention

Same 3 prompts, run while a background process kept `faster-whisper
medium.en` (STT) and Piper (TTS) continuously busy transcribing/
synthesizing in a loop (`poc/contention_load.py`), approximating a live
pipeline where STT/TTS are also active. Full data:
`results/llm_bench_contention.json`.

| Model | cold-load (warmup) | avg first-token | avg total (per prompt) | avg tok/s |
|---|---|---|---|---|
| `qwen2.5:32b` | 9.99s | 0.49s | 8.39s | 9.01 |
| `gemma2:27b` | 7.69s | 0.61s | 6.05s | 9.92 |

**Both models were essentially unaffected by STT/TTS contention** —
first-token latency, total latency, and tok/s are all within noise of the
isolated numbers (a few percent, well inside run-to-run variance seen in
the isolated numbers themselves). This makes sense given Finding 0: LLM
inference runs on GPU while STT (CPU-only) and TTS (mostly CPU) compete
for a different resource pool. The STT contention loop itself only
slowed mildly (~4.0s→~4.7s per clip, ~7.3s→~8.5s for the noisy clip) as
both LLMs loaded/ran — no repeat of the severe multi-minute stall from
`stt_benchmark.md`'s Finding 1.

**Important scope note on that non-finding**: cold-loading `gemma2:27b`
while `qwen2.5:32b` was already resident (19GB + 15GB, well under 48GB)
was **not** a repeat of the Finding-1 danger zone — no stall, comparable
cold-load time to isolated. The earlier severe-stall incident specifically
involved `large-v3` STT (via `ctranslate2`, CPU-only, high peak transient
memory during its own load) cold-loading alongside an already-generating
LLM. This benchmark's contention scenario (one resident LLM + a *different*
LLM cold-loading + STT/TTS looping, all comfortably inside 48GB) did not
reproduce it. Read together with `setup.md`/`stt_benchmark.md`: the risk
factor is specifically large transient memory spikes during a cold load
pushing total footprint close to the 48GB ceiling, not simply "two models
active at once."

## Memory / resource footprint (`ollama ps` while loaded & generating)

| Model | Reported size | Processor | Context window |
|---|---|---|---|
| `qwen2.5:32b` | 28 GB | 100% GPU | 32768 tokens |
| `gemma2:27b` | 16 GB | 100% GPU | 8192 tokens |

`qwen2.5:32b`'s larger reported footprint is driven mostly by its default
32K context window (4x `gemma2:27b`'s 8K) — the on-disk weights are
19GB vs 15GB, not a 28GB vs 16GB gap. This context-window difference is
worth carrying into EPIC-02/03 design: `qwen2.5:32b` has more headroom
for long conversation history before needing summarization/truncation,
at the cost of a bigger permanent memory reservation while loaded (which
matters for `STORY-01-07`'s barge-in feasibility math, since that story
also needs headroom for a concurrently-running STT/VAD pass).

## Quality — draft persona-prompt conversation check

Ran a short (8-turn) scripted free-form conversation through both models
using a **draft** proactive-persona system prompt (not the final one —
that's `STORY-01-06`'s job), deliberately including passive/deflecting
user turns ("I don't know, what do you want to talk about?", "what about
you?") to stress-test proactivity. Full transcripts:
`results/persona_transcripts_draft/{qwen2.5_32b,gemma2_27b}.md`.

**Both models stayed proactive throughout** — neither went flat or
started passively waiting on the user; both consistently asked
follow-up questions and introduced new topics (movies → travel/food) when
the user deflected. Over only 8 turns neither showed the "regression to
generic-assistant tone" pattern `STORY-01-06` is specifically designed to
check for at longer session lengths (15-20 turns) — that remains
`STORY-01-06`'s job to verify properly.

**⚠️ One notable quality difference**: when the scripted user turned the
question back ("What about you, do you like movies?"), `gemma2:27b`
broke character, explicitly saying *"As a language model, I can't watch
them in the traditional sense..."* — a direct persona break that would be
jarring in a real conversation-practice product. `qwen2.5:32b` handled
the same prompt by staying in character ("I love movies! If I could, I'd
probably watch a new one every day...") — evasive on the specifics but
did not break the fourth wall. This is a real signal in `qwen2.5:32b`'s
favor for persona adherence and should be re-checked at longer session
length in `STORY-01-06`.

Both models produced natural, conversational (not stilted) English and
neither refused persona commitment or lectured/corrected the user's
casual phrasing — good on the "no unnatural/stilted English" and
"no unwanted correction" checks from this story's tasks.

## Recommendation

- **`qwen2.5:32b` as the default/leading candidate**, primarily on the
  persona-break finding above (`gemma2:27b`'s "as a language model" slip)
  — latency/tok-per-s are close enough between the two (within ~10%) that
  quality/persona-adherence is the deciding factor, consistent with this
  story's goal ("quality — not just raw benchmark numbers").
- `gemma2:27b` is not disqualified — it's faster to cold-load (7.6-7.7s
  vs ~10s), has a smaller idle memory footprint, and produced comparably
  natural English. It's a reasonable candidate to **reserve for the
  learning-layer's non-critical-path LLM pass** (EPIC-04 / ADR-0003),
  where a persona break doesn't matter and the smaller footprint leaves
  more headroom for the primary conversational LLM to stay resident.
- Both candidates run 100% GPU on this hardware and were unaffected by
  STT/TTS contention in this benchmark — LLM latency is not currently the
  pipeline's bottleneck; STT remains the open budget problem
  (`stt_benchmark.md` Finding 2, still pending STORY-01-05).
- Feed the persona-break finding directly into `STORY-01-06`: re-test
  both models' persona adherence at the full 15-20 turn length before
  finalizing the choice, since 8 turns may not be enough to see the full
  pattern (in either direction).
