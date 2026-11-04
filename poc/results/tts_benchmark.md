---
story: STORY-01-04
status: complete
updated: 2026-09-03
---

# STORY-01-04 — TTS latency & voice quality benchmark: results

## Test setup

4 short conversational sentence-chunks (simulating streamed, per-sentence
TTS output rather than a whole response synthesized at once — the
realistic streaming use case):

1. "That sounds like a really frustrating situation with your neighbor."
2. "Have you thought about what you'd actually say to him?"
3. "I think staying calm is going to matter more than being right."
4. "Let's practice how you might start that conversation."

Engines/voices tested:
- **Piper**: `en_US-lessac-medium` (US male), `en_GB-alan-medium` (GB
  male), `en_US-amy-medium` (US female) — the 3 voices installed in
  `STORY-01-01`.
- **XTTS v2**: stock built-in speaker (`Claribel Dervla`, one of 58
  bundled speakers, no cloning) and a **cloned** voice, cloned from
  `samples/test_input.wav` (the clean macOS `say -v Samantha` reference
  used for STT smoke tests in `STORY-01-01`).

Samples saved to `results/tts_samples/`.

## Latency (per-chunk, avg over the 4 chunks)

| Engine / voice | avg latency | notes |
|---|---|---|
| Piper `en_US-lessac-medium` | **0.59s** | includes per-call process startup (`uv run python -m piper`); a warm long-running process would likely be faster |
| Piper `en_GB-alan-medium` | **0.58s** | |
| Piper `en_US-amy-medium` | **0.59s** | |
| XTTS v2 stock (`Claribel Dervla`) | **1.56s** | model loaded once, timing excludes load |
| XTTS v2 cloned (from `test_input.wav`) | **2.17s** | same model instance, cloning adds ~0.6s over stock |

**Piper is ~2.6-3.7x faster than XTTS v2** per sentence-chunk, consistent
across all 3 voices (voice choice barely affects Piper's latency).

## Quality — listened live with Andrey (chunk 2: "Have you thought about what you'd actually say to him?")

All 5 samples played back-to-back through speakers for a direct
comparison. Andrey's live feedback:

- **Most natural/pleasant on first listen: XTTS stock (Claribel)** — but
  on reflection, **"Piper даже приятнее звучал"** ("Piper actually
  sounded even nicer") — i.e. **the gap is small and inconsistent, not
  a clear win for either engine.** This matters: XTTS's ~2.6-3.7x higher
  latency is not obviously bought back by a clearly better listening
  experience.
- **Voice cloning (XTTS, from the Samantha reference): recognizable
  resemblance to the reference voice, but with audible artifacts.**
  Confirmed by Andrey directly ("похоже, но с артефактами").

No formal MOS-style scoring done — not needed at this rough-check level
per the story's own scope; Andrey's direct A/B reaction is the signal
that matters for a single-user product.

## Is XTTS v2 chunked streaming practical at the latency budget?

**No, not as the default.** Even the fastest single XTTS chunk observed
in this test was 1.35s — on its own, larger than the PRD's whole ≤1.5s
TTFA budget (`CLAUDE.md` rule 5), before VAD+STT+LLM have contributed
anything. Piper's ~0.6s per chunk leaves meaningfully more of that
budget for the rest of the pipeline. (Not retested under LLM+TTS
contention specifically for this story — Piper already ran concurrently
during the `STORY-01-02`/`stt_engine_spike` contention tests without
issue, which is a reasonable proxy that it holds up.)

## Recommendation

- **Default TTS engine: Piper.** Faster by a wide margin, and — per
  Andrey's direct listening test — not clearly worse-sounding than XTTS
  v2, sometimes preferred. This is the one to build the live
  conversational pipeline around.
- **XTTS v2 (stock speakers): keep as an optional non-default mode**,
  e.g. for a specific character/persona voice where the extra ~1s/chunk
  latency is an acceptable tradeoff outside the tightest real-time path
  (not for the primary live-conversation turn).
- **Voice cloning: defer, do not ship in the near term.** Slowest option
  tested and the only one with audible artifacts confirmed by Andrey.
  Revisit only if there's a specific concrete need for a cloned target
  voice later — no evidence here that it's worth the latency+quality
  cost for the default experience.
