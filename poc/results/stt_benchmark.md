---
story: STORY-01-02
status: complete
updated: 2026-09-03
---

# STORY-01-02 — STT latency & accuracy benchmark: results

## Test data

5 real speech clips recorded from Andrey via MacBook Pro built-in mic
(`ffmpeg` + AVFoundation, 16kHz mono WAV, ~15s each), covering the range
the story asked for — not clean benchmark-optimized audio:

| Clip | Condition |
|---|---|
| `clip1_normal.wav` | Normal pace, quiet room |
| `clip2_noise.wav` | Background noise (music/TV) while talking |
| `clip3_fast.wav` | Fast/casual conversational speech |
| `clip4_technical.wav` | Content-dense (dialogue with names, no jargon read) |
| `clip5_freeform.wav` | Free-form, normal pace |

Content: Andrey narrated an "advice column" scenario (neighbor noise
complaint) across the 5 clips — natural, spontaneous, non-native-accented
English, several sentences cut off mid-thought by the 15s recording
limit (expected and fine — it stresses truncated-utterance handling too).

Accuracy check: transcripts were read back to Andrey; confirmed as
"похоже на правду" (accurate) for both `medium.en` and `large-v3`, which
agreed almost word-for-word on all 5 clips (differences limited to
punctuation/capitalization, e.g. "make" vs "makes", "when you" vs
"when you're"). No formal WER computed — not needed at this rough-check
level per the story's own scope.

## Latency — isolated (STT only, nothing else loaded)

| Model | clip1 | clip2 | clip3 | clip4 | clip5 | **avg** |
|---|---|---|---|---|---|---|
| `medium.en` | 5.50s | 9.63s | 5.87s | 5.90s | 5.65s | **6.51s** |
| `large-v3` | 9.85s | 9.83s | 10.73s | 10.44s | 10.31s | **10.23s** |

(Full clip-to-transcript latency, ~15s of audio each — not a streaming
partial-decode measurement. `device="cpu", compute_type="int8"` —
`ctranslate2` has no Apple Silicon GPU backend, see `setup.md`.)

## Latency — under resource contention

Same 5 clips, transcribed while `qwen2.5:32b` was actively generating a
long response via Ollama **and** Piper TTS was synthesizing in a loop —
approximating a live pipeline where STT has to run while the assistant's
previous turn is still being generated/spoken.

| Model | clip1 | clip2 | clip3 | clip4 | clip5 | **avg** |
|---|---|---|---|---|---|---|
| `medium.en` | 17.11s | 34.51s | 19.61s | 22.32s | 46.85s | **28.08s** |
| `large-v3` | **539.30s** ⚠️ | 19.57s | 12.09s | 8.25s | 7.96s | 11.97s (excl. outlier) |

Memory during this run: `Swapouts` counter rose by ~230k pages (~3.6GB
swapped) over the test window; system stayed up, Ollama stayed
responsive, no crash (contrast with the `llama3.3:70b` incident in
`setup.md` — see finding below on why).

## ⚠️ Finding 1: a 539-second stall on `large-v3`'s first load under contention

The very first `large-v3` transcription under contention took **9
minutes**, then every subsequent clip (still under the same contention)
was back to a normal 8-20s. This lines up with `large-v3` being loaded
into memory for the first time in this process while `qwen2.5:32b`
(19GB) was already resident and actively generating — the *model load*,
not steady-state inference, was what triggered severe swap thrashing.
Once loaded and warm, it recovered.

**Read**: memory pressure doesn't fail cleanly — it produces wildly
unpredictable tail latency (9 min instead of ~10s) before recovering,
rather than crashing outright. This is arguably worse for a real-time
UX than a clean failure. Combined with the `llama3.3:70b` OOM finding in
`setup.md`, the pattern is consistent: **cold-loading any model while
another large model is already resident is the danger zone**, whether or
not the combined footprint technically fits in 48GB.

## ⚠️ Finding 2: neither model is remotely close to the ≤250ms VAD+STT budget

Even in the **best case** (isolated, `medium.en`, no contention): 5.5–9.6s
to transcribe a ~15s clip. Scaling down to a more realistic single
conversational turn (~3-5s of speech) would still land in the
**1–3 second range** at the same processing ratio — 4–12x over the PRD's
≤250ms VAD+STT budget (`CLAUDE.md` workflow rule 5), before contention is
even factored in. Under contention, `medium.en` alone averaged 28s per
clip.

This is a genuine budget-vs-reality gap that needs to be raised, not
worked around silently (`CLAUDE.md` rule 8). Two components feed into it:
1. **No GPU backend for STT on this hardware** — `ctranslate2` is
   CPU-only on Apple Silicon, so `faster-whisper` can't use the M4 Pro's
   GPU/ANE at all.
2. **This measures full-clip batch decode, not streaming partial
   decode** — the real pipeline would presumably decode incrementally as
   speech arrives, which the PRD's budget likely assumes. This PoC did
   not test streaming/chunked STT — flagging as a gap for STORY-01-05
   (end-to-end pipeline) to specifically address, since it changes the
   picture significantly.

## Recommendation

- **`medium.en` over `large-v3`** for this project: ~40% faster in
  isolation, ~2.4x faster under contention (excluding the outlier), and
  accuracy was indistinguishable from `large-v3` on these 5 samples at
  the rough-check level. `large-v3`'s extra accuracy doesn't currently
  buy anything given both were already confirmed accurate.
- **The ≤250ms VAD+STT budget needs revisiting** — recommend STORY-01-05
  (end-to-end pipeline) specifically test streaming/chunked
  `faster-whisper` decoding (partial results as audio arrives) before
  concluding the budget is unreachable; if streaming doesn't close the
  gap, this needs an ADR revising the PRD budget (`CLAUDE.md` rule 5) —
  do not silently ship a slower budget without recording it.
- **Never cold-load a second large model while one is already resident**
  under real-time constraints — either keep exactly one LLM warm for the
  whole session, or accept a multi-second/-minute stall as the cost of
  switching. This directly informs STORY-01-07 (barge-in feasibility)
  and the eventual server's model-lifecycle design.
