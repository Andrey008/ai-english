---
story: STORY-01-01
status: complete
updated: 2026-09-02
---

# STORY-01-01 — Environment & model setup: results

## Hardware / OS

- MacBook Pro, Apple M4 Pro, 48 GB RAM
- macOS 26.5.1 (build 25F80)
- Disk: 460Gi total, ~91Gi free at start of PoC setup

## Base tooling (already present, no install needed)

| Tool | Version |
|---|---|
| Homebrew | 6.0.20 |
| uv | 0.11.14 |
| Ollama | 0.33.0 |

Installed during this story:

| Tool | Version | Why |
|---|---|---|
| ffmpeg | 9.0.1 (Homebrew) | required by `torchcodec` for audio I/O (XTTS v2 dependency chain) |

## Python project

- `/poc` — uv-managed project, pinned to **Python 3.11** (`.python-version`)
  (chosen over 3.12+ for best compatibility with the STT/TTS stack at
  setup time; nothing here needed 3.14, the Homebrew default)
- Dependencies pinned in `pyproject.toml` / `uv.lock`

### Key package versions

| Package | Version |
|---|---|
| faster-whisper | 1.2.1 |
| ctranslate2 | 4.8.2 |
| silero-vad | 6.2.1 |
| coqui-tts | 0.27.5 |
| piper-tts | 1.7.0 |
| torch | 2.13.0 |
| torchaudio | 2.11.0 |
| torchcodec | 0.16.0 |
| transformers | **4.57.6 (pinned `<5`)** — see note below |
| ollama (python client) | 0.6.2 |
| numpy | 2.4.6 |

## Setup notes / gotchas (for reproducibility)

- **`coqui-tts` breaks on `transformers>=5`**: `coqui-tts` 0.27.5 declares
  `transformers>=4.57` but its Tortoise/XTTS autoregressive layer imports
  `isin_mps_friendly` from `transformers.pytorch_utils`, which was removed
  in transformers 5.x. Fixed by pinning `transformers<5` (resolved to
  4.57.6). Revisit if upgrading coqui-tts later.
- **`torchcodec` requires a system ffmpeg** (torch 2.9+ dropped bundled
  audio I/O). Installed via `brew install ffmpeg` (pulled ffmpeg 9.0.1,
  libavutil 61). Without it, XTTS v2 import fails with
  `ImportError: TorchCodec is required for audio IO`.
- **`silero-vad`'s own `read_audio()` helper also needs torchcodec** and
  is a bit fragile; smoke test instead loads the wav via `soundfile` +
  `torch.from_numpy` and passes the tensor directly to
  `get_speech_timestamps`. Keep this pattern for later stories.
- **STT (`faster-whisper`) runs CPU-only** — `ctranslate2` has no Apple
  Silicon GPU (Metal/MPS) backend, so `device="cpu", compute_type="int8"`
  is the only option on this hardware. This directly affects the latency
  budget validation in STORY-01-02 — flag if CPU-only STT can't hit the
  budget.

## Disk-space risk (flagged to user, confirmed to proceed)

At setup time only ~91GB was free, and Ollama already held two unrelated
models (`qwen3.8:27b`, 17GB; `qwen3-coder:30b`, 18GB — a coding model, not
relevant to this project). The full 3-model LLM candidate set for
STORY-01-03 (`qwen2.5:32b` ~19GB, `llama3.3:70b` ~42GB, `gemma2:27b`
~15GB, per Ollama's own manifest sizes) needed ~76GB more. User confirmed
proceeding with the full set as originally scoped in STORY-01-01. Disk
should be monitored during Phase 1 — very little headroom remains once all
three are pulled.

## Components installed & smoke-tested

| Component | Smoke test | Result |
|---|---|---|
| STT — faster-whisper `medium.en` | `smoke_stt.py medium.en` — transcribe a synthesized "test sentence" wav | **PASS** (load 73.0s incl. first download, infer 3.3s) |
| STT — faster-whisper `large-v3` | `smoke_stt.py large-v3` | **PASS** (load 142.6s incl. first download, infer 5.8s) |
| VAD — silero-vad | `smoke_vad.py` — detect speech segments in same sample | **PASS** (2 segments found, 0.0–0.6s and 0.7–4.0s) |
| TTS — Piper (`en_US-lessac-medium`) | `smoke_piper` (manual CLI) — synthesize test sentence | **PASS** (4.09s WAV @ 22.05kHz) |
| TTS — Piper (`en_GB-alan-medium`) | same | **PASS** |
| TTS — Piper (`en_US-amy-medium`) | same | **PASS** |
| TTS — XTTS v2 (coqui-tts), voice cloning | `smoke_xtts.py` — clone from the same test sample, synthesize new sentence | **PASS** (load 17.2s, infer 7.3s, 258KB output) |
| LLM — Ollama client (`qwen3.8:27b`, pre-existing model) | `smoke_llm.py qwen3.8:27b` — round-trip "reply PONG" | **PASS** (14.95s) |
| LLM — `qwen2.5:32b` (candidate) | `smoke_llm.py qwen2.5:32b` | **PASS** (10.04s) |
| LLM — `gemma2:27b` (candidate) | `smoke_llm.py gemma2:27b` | **PASS** (3.10s) |
| LLM — `llama3.3:70b` (candidate) | `smoke_llm.py llama3.3:70b` | **PASS, but see finding below** (290.59s — 1st attempt crashed) |

Voices downloaded to `/poc/voices/` (Piper, `.onnx` + `.onnx.json` each):
`en_US-lessac-medium`, `en_GB-alan-medium`, `en_US-amy-medium`.

Test sample: `/poc/samples/test_input.wav` (16kHz mono, generated via
macOS `say -v Samantha`, 4.0s, known transcript
"Hello, this is a test sentence for the proof of concept pipeline.").

Final Ollama model IDs (`ollama list`):

| Model | ID | Size |
|---|---|---|
| `llama3.3:70b` | `a6eb4748fd29` | 42 GB |
| `qwen2.5:32b` | `9f13ba1299af` | 19 GB |
| `gemma2:27b` | `53261bc9c192` | 15 GB |
| `qwen3.8:27b` (pre-existing, used for early client smoke test only) | `22130167c4c2` | 17 GB |

## ⚠️ Finding: `llama3.3:70b` is not viable on this hardware — flag for STORY-01-03 / ADR-0004

On first `smoke_llm.py llama3.3:70b` run, the `llama-server` process was
**killed by the OS** (`ollama._types.ResponseError: llama-server process
has terminated: signal: killed`) partway through a trivial "reply PONG"
request — consistent with an OOM kill.

On retry, it did complete, but only after **290.59 seconds** for a
one-word reply (vs. 10.04s for `qwen2.5:32b` and 3.10s for `gemma2:27b` —
roughly **30–100x slower**). While loaded, `llama-server` RSS climbed to
~37GB (peak observed ~50GB via `top`) against 48GB total unified memory,
free pages dropped to near-zero, and `vm_stat` showed heavy, sustained
swap activity (~13GB of swap I/O in a 2-minute window).

**Read**: at Q4 quantization (42GB on disk), `llama3.3:70b` leaves almost
no headroom in 48GB of unified memory once macOS itself, and any other
pipeline component (STT/TTS/VAD models, the OS, apps), are accounted for.
The model is technically loadable but **not usable within any real-time
latency budget** — this directly conflicts with the PRD's TTFA ≤ 1.5s
target (`CLAUDE.md` workflow rule 5) and is far outside the range where
barge-in (`STORY-01-07`) could plausibly work.

This is a setup-stage signal, not a final verdict — STORY-01-03 does the
proper LLM latency/quality benchmark and should treat `llama3.3:70b` as
**very likely disqualified on resource grounds** on this machine, and
confirm whether `qwen2.5:32b` or `gemma2:27b` (both fast and stable here)
meet the quality bar instead. If `llama3.3:70b` is dropped, note that in
STORY-01-08's findings report and reflect it in ADR-0004 / PRD budget
discussion.

**Update (2026-09-03):** during this same window the OS killed enough
background processes under memory pressure that Andrey lost time
recovering the machine (had to reboot to get things stable again) — the
jetsam/OOM behavior above wasn't just theoretical, it visibly took down
other running apps too. Given that plus the 290s response time, the
decision is made now rather than deferred to STORY-01-03:
**`llama3.3:70b` is dropped from the LLM candidate set.** It has been
removed from Ollama (`ollama rm llama3.3:70b`, freed 42GB). STORY-01-03
benchmarks only `qwen2.5:32b` and `gemma2:27b` going forward. If a
70B-class model is ever revisited, it needs a hard memory guard (e.g. a
pre-flight free-RAM check, or simply never running it alongside anything
else) — not just "try it and see."

## Remaining for this story

None — all tasks and acceptance criteria complete.
