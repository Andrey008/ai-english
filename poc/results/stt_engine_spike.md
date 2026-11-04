---
addendum-to: STORY-01-05 (folded in early, before STORY-01-05 itself starts)
related: STORY-01-02 (STT benchmark), Docs/STATUS.md → "Open questions"
status: complete (batch + streaming both tested)
updated: 2026-09-03
---

# STT-engine spike — GPU/ANE-capable alternatives to faster-whisper

## Why this exists

`STORY-01-02` found the PRD's ≤250ms VAD+STT budget unreachable with
`faster-whisper`/`ctranslate2` (CPU-only on Apple Silicon — see
`stt_benchmark.md` → Finding 2). Before writing an ADR revising that
budget, we need to check whether the bottleneck is `ctranslate2`
specifically (not Whisper models in general) by trying engines that CAN
use the M4 Pro's GPU (Metal) and/or Neural Engine/ANE (Core ML).
Recorded as an open question in `Docs/STATUS.md`.

## Plan

1. Install `whisper.cpp`.
2. Get/convert a `medium.en`-equivalent model with Core ML support
   (ANE-capable) — this is the main candidate, since ANE is
   purpose-built for neural-net inference and not currently used
   anywhere in the pipeline.
3. Benchmark on the same 5 real-voice clips as `STORY-01-02`
   (`poc/samples/real_voice/clip{1..5}*.wav`), both isolated and (if
   time permits) under the same LLM+TTS contention setup used in
   `STORY-01-03`.
4. Compare latency against the `faster-whisper` numbers in
   `stt_benchmark.md`, and compare transcripts for accuracy
   (word-for-word against the STORY-01-02 transcripts).
5. If whisper.cpp/Core ML closes the gap: recommend switching STT engine,
   update `STORY-01-02`'s recommendation and feed into `STORY-01-05`.
   If not: try MLX Whisper next. If neither closes it: this is the
   evidence needed to write the ADR revising the VAD+STT budget.

## Progress log

- 2026-09-03: Spike started. Plan above agreed with Andrey (test
  whisper.cpp + Core ML/ANE first, keep this doc updated as we go).
- 2026-09-03: `cmake` installed via Homebrew (not previously present).
  Cloned `whisper.cpp` into `poc/whisper.cpp/` (gitignored — vendored
  external tool, not our code). Created an isolated Python 3.11 venv
  (`poc/whisper.cpp/.coreml-venv/`, also gitignored via `.venv`-style
  pattern — separate from the main `poc` uv env to avoid torch-version
  conflicts) and installed `ane_transformers`, `openai-whisper`,
  `coremltools` there.
- 2026-09-03: Ran `./models/generate-coreml-model.sh medium.en`. The
  PyTorch→Core ML conversion itself **succeeded** (downloaded
  `medium.en.pt`, traced and converted to MIL/`.mlpackage` without
  errors). It then failed at the final compile step:
  `xcrun: error: unable to find utility "coremlc"`.

## ⚠️ Blocker: `coremlc` requires full Xcode.app, not just Command Line Tools

`coremlc` (the tool that compiles a `.mlpackage` into the `.mlmodelc`
whisper.cpp actually loads) ships with the full **Xcode.app**, not the
lightweight Command Line Tools we have installed
(`/Library/Developer/CommandLineTools`). Xcode.app is a large
(~10-15GB) download from the App Store / Apple Developer site.

Given this project's own disk-space flag from `STORY-01-01`
(`setup.md` — "very little headroom remains once all three [LLM] models
are pulled"), installing full Xcode is a real resource decision, not a
transparent formality — pausing here to confirm with Andrey before
downloading it, rather than doing it silently (`CLAUDE.md` rule 8).

**Options to unblock, in order of preference:**
1. Install full Xcode.app (~10-15GB) — cleanest path, gives us
   `coremlc` and unlocks the intended benchmark.
2. Try MLX Whisper instead (no Xcode dependency, though it uses GPU via
   Metal rather than ANE specifically — still answers the "is
   `ctranslate2` uniquely the problem" question, just not the
   ANE-specific one).
3. Skip the Core ML/ANE path for now, note it as untested, and move
   forward with MLX Whisper and/or `SFSpeechRecognizer` results alone.

**Decision (2026-09-03): install full Xcode.app.** Requires Andrey's
Apple ID / manual App Store interaction — cannot be scripted/automated.
App Store opened to the Xcode page; waiting on the install to finish
before resuming the Core ML compile step.

- 2026-09-03: Xcode 26.6 finished installing (license already accepted,
  no interactive prompt needed). Resumed from the existing `.mlpackage`
  (no reconversion needed): `xcrun coremlc compile
  models/coreml-encoder-medium.en.mlpackage models/`, renamed the output
  to `models/ggml-medium.en-encoder.mlmodelc` per whisper.cpp's
  convention. Built with `cmake -B build -DWHISPER_COREML=1 && cmake
  --build build -j --config Release` — Metal, BLAS/Accelerate, and
  CoreML backends all detected and built successfully. Downloaded
  `ggml-medium.en.bin` (1.4GB) via `models/download-ggml-model.sh`.
- 2026-09-03: Ran the same 5 real-voice clips from `STORY-01-02`
  (`poc/samples/real_voice/clip{1..5}*.wav`) through
  `./build/bin/whisper-cli -m models/ggml-medium.en.bin -f <clip>`,
  isolated (2 passes, to separate one-time ANE compile warmup from
  steady state) and under the same LLM+TTS contention setup as
  `STORY-01-02`/`STORY-01-03` (`qwen2.5:32b` generating + Piper
  synthesizing concurrently). Memory watched throughout per Andrey's
  request after the `llama3.3:70b` incident — stayed stable, no crash,
  no runaway swap (see Memory/stability note below).

## Results

`system_info` confirmed `COREML = 1` (Core ML backend loaded and used
for the encoder) alongside Metal/GPU for the rest of the pipeline.
**Correction (2026-09-03, after Andrey asked directly whether ANE was
actually confirmed):** `COREML = 1` means the Core ML *path* is active,
not specifically that the ANE is doing the work — whisper.cpp configures
`MLComputeUnitsAll`, letting Core ML pick CPU/GPU/ANE. Attempted to
verify ANE usage empirically via `powermetrics --samplers ane_power`
(twice, with Andrey running it under sudo) — this Mac/macOS combination
produced no ANE data at all, a tooling limitation rather than a
negative result. Indirect evidence (GPU idle residency staying 85-95%
during near-continuous inference, plus the ~1.5s encode time vs. ~5-10s
for CPU-only `ctranslate2`) suggests the ANE is very likely doing
meaningful work, but this is **not confirmed** — see the fuller writeup
in `Docs/STATUS.md` → "Compute backend audit." Doesn't change the
recommendation below (the measured latency win is real and directly
measured either way), but avoid restating "ANE encoder active" as a
settled fact.

**Isolated latency** (whisper.cpp CoreML `medium.en`, "total time" per
clip, steady state / pass 2):

| Clip | whisper.cpp+CoreML | faster-whisper `medium.en` (STORY-01-02) |
|---|---|---|
| clip1_normal | 1.42s | 5.50s |
| clip2_noise | 1.86s | 9.63s |
| clip3_fast | 1.53s | 5.87s |
| clip4_technical | 1.54s | 5.90s |
| clip5_freeform | 1.45s | 5.65s |
| **avg** | **1.56s** | **6.51s** |

**→ ~4.2x faster in isolation.** Pass 1 (including the one-time
"first run on a device" ANE compile step) was barely different from pass
2 (1.40–1.88s vs 1.42–1.86s) — the ANE compile overhead is negligible
here, likely because it had already happened during an earlier manual
sanity-check run before this benchmark script ran; worth re-verifying
from a fully cold state if this engine moves into the real server.

**Contention latency** (LLM generating + TTS synthesizing concurrently):

| Clip | whisper.cpp+CoreML | faster-whisper `medium.en` (STORY-01-02) |
|---|---|---|
| clip1_normal | 7.01s | 17.11s |
| clip2_noise | 4.66s | 34.51s |
| clip3_fast | 5.11s | 19.61s |
| clip4_technical | 4.16s | 22.32s |
| clip5_freeform | 3.80s | 46.85s |
| **avg** | **4.95s** | **28.08s** |

**→ ~5.7x faster under contention**, and critically: **no repeat of the
539-second stall** seen when `faster-whisper`'s `large-v3` cold-loaded
under contention in `STORY-01-02`. whisper.cpp's memory footprint is
much smaller than `ctranslate2`'s, which is the likely reason.

**Accuracy**: transcripts read essentially identical in content/quality
to the `faster-whisper` transcripts from `STORY-01-02` (same clips,
same content understood correctly, same minor artifacts like the 15s
recording cutoffs). No regression from switching engines.

**Memory/stability**: `Swapouts` grew during the contention run (as
expected with `qwen2.5:32b` + Piper + whisper.cpp all active at once)
but `Pages free` recovered to a healthy level after each clip, no OOM
kill, no multi-minute stall, Ollama stayed responsive throughout, and
`ollama list` confirmed no crash afterward. Confirms the earlier
`STORY-01-02` read: the danger zone is specifically *cold-loading a new
large model* while another is resident, not simply having multiple
models active together.

## Recommendation

**Switch the STT engine recommendation from `faster-whisper` to
`whisper.cpp` with Core ML (ANE) for `medium.en`.** This supersedes
`STORY-01-02`'s recommendation (which correctly picked `medium.en` over
`large-v3`, but as a `faster-whisper` model — the *engine* choice is
what changes here, not the model size). Confirms the STORY-01-02
Finding 2 hypothesis: the latency bottleneck was `ctranslate2`
specifically lacking an Apple Silicon GPU/ANE backend, not Whisper
models being inherently too slow for this hardware.

**Does this close the ≤250ms VAD+STT budget gap? Partially, not fully.**
- It's a ~4-6x improvement, which is a big deal, but 1.56s (isolated) /
  4.95s (contention) is still well over 250ms for these ~15s clips.
- These are **full-clip batch decode** numbers, same caveat as
  `STORY-01-02`. Scaling by the observed real-time factor (~0.10x
  isolated, ~0.33x contention) to a more realistic single conversational
  turn (~3s of speech) gives a rough estimate of ~0.3s isolated /
  ~1.0s contention — much closer to budget in isolation, but this is an
  extrapolation, not a measurement, and doesn't account for
  streaming/incremental decode which the PRD budget likely assumes.
- **whisper.cpp has a genuine streaming example** (`examples/stream`)
  that decodes incrementally as audio arrives, which is the actually
  correct comparison for a ≤250ms *incremental* budget — this spike only
  tested batch (`whisper-cli`) mode. Testing streaming mode is the
  natural next step and is explicitly in scope for `STORY-01-05`
  (end-to-end pipeline) rather than repeating it here.
- MLX Whisper and `SFSpeechRecognizer` were not tested — given the
  strong result here and that further comparison is better done in the
  full pipeline context (`STORY-01-05`) with streaming decode, this
  spike stops here rather than continuing down the candidate list.

**Bottom line for the pending ADR**: don't write the "PRD budget is
unreachable" ADR yet — `whisper.cpp`+CoreML batch mode alone closes
most of the gap, and streaming mode (untested here) could close the
rest. `STORY-01-05` should test streaming `whisper.cpp` on the real
pipeline before that ADR is written; if streaming still can't hit
≤250ms, write the ADR then, with this spike's numbers as part of the
evidence for how much budget to actually propose.

## Addendum (2026-09-03): streaming decode tested — big further improvement

After `STORY-01-05` measured the full pipeline (batch STT was 39% of a
6.37s median TTFA, `/poc/results/e2e_latency.md`), asked by Andrey to
follow up on the untested streaming path before writing the budget ADR.

**Setup**: rebuilt with `-DWHISPER_SDL2=ON` (SDL2 already present via
Homebrew), producing `whisper-stream`. Ran in sliding-window VAD mode
(`--step 0 --length 8000 -vth 0.6`, `medium.en`+CoreML) listening on the
MacBook's built-in mic. **Methodology**: rather than live speech (hard to
timestamp precisely from a chat-mediated session), played the 5
VAD-trimmed real-voice clips (`*_trimmed.wav`, already cut exactly at
detected speech-end from `STORY-01-05`) through the **speakers**
(Andrey switched audio output from headphones for this) so the mic
picked them up acoustically — `afplay`'s return time (blocks until
playback finishes) is therefore a precise proxy for "speech just ended,"
matched against the wall-clock timestamp `whisper-stream` printed its
next transcription at.

**Results** — latency from speech-end to printed transcript:

| Clip | Latency |
|---|---|
| clip1_normal | 0.503s |
| clip2_noise | 0.520s |
| clip3_fast | 0.806s |
| clip4_technical | 0.540s |
| clip5_freeform | 0.846s |
| **avg** | **0.643s** |
| **median** | **0.540s** |

**→ another ~2.4-4.7x faster than batch mode** (1.56s isolated / 2.55s
in the `STORY-01-05` pipeline context) — and combined with the original
`faster-whisper`→`whisper.cpp` switch, **streaming+CoreML is now
roughly 10x+ faster than where this all started** (`faster-whisper`
batch, 6.51s avg in `STORY-01-02`).

**Does streaming close the ≤250ms gap? Closer, but still no — median
540ms is ~2.2x over.** Two caveats on the honest side: (1) this is a
5-sample spike, not a rigorous distribution; (2) `whisper-stream`'s own
architecture polls/re-evaluates VAD periodically rather than being
purely event-driven at the sample level, so some further tuning
headroom may exist, untested here (out of scope for a spike). Accuracy
looked consistent with earlier runs, with one expected side-effect: the
8s sliding window truncated the start of longer utterances (e.g. clip1's
opening sentence) — not a latency concern, but worth noting for a real
implementation's buffer sizing.

**Updated recommendation**: switch to **`whisper.cpp` streaming mode**
(not just CoreML batch) as the real STT design for `STORY-01-05`'s
successor work / EPIC-02. This closes most of the remaining gap the
batch-mode recommendation left open. **The PRD budget ADR should now be
written** — 540ms median streaming STT, on top of LLM (~1s) and TTS
(~1-3s) time-to-first-chunk, still puts realistic end-to-end TTFA well
above 250ms for STT alone and above 1.5s in total, so ≤1.5s TTFA and
≤250ms VAD+STT both need revising with these numbers as the evidence
base — but the revised number should reflect streaming STT, not the
batch numbers `STORY-01-05`'s pipeline used (that pipeline should
itself be revisited to use streaming STT for its own more accurate TTFA
figure, as a candidate future refinement rather than blocking the ADR).
