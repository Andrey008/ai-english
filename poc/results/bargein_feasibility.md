---
story: STORY-01-07
status: complete
updated: 2026-09-03
---

# STORY-01-07 — Barge-in resource-feasibility spike: results

## Setup

`poc/bargein_spike.py`: LLM (`qwen2.5:32b`, streamed) generating a
longer response (4-6 sentences) while Piper synthesizes and plays each
sentence via `afplay`, **while a continuous background thread listens on
the live mic** via `silero-vad`'s `VADIterator` (chunk-by-chunk, 32ms
frames, threshold 0.5) for the onset of new speech — the actual barge-in
condition: VAD/STT-ready while LLM+TTS are both active, not a
sequential/idle-mic test.

On detecting speech onset, the script immediately kills the active
`afplay` process and stops consuming further LLM stream output. Andrey
(on headphones, to avoid speaker→mic acoustic feedback confounding the
test) interrupted deliberately at varying points in each cycle.

Two runs:
1. **5 cycles**, quick succession (~35s total) — initial validation.
2. **8 cycles / 142s** of sustained concurrent LLM+TTS+VAD load — the
   "realistic session length" endurance check the story's task 4 asks
   for, with continuous memory sampling throughout.

## Results

### Stop latency (VAD-detected speech onset → TTS playback confirmed killed)

**13 real interrupt events** across both runs:

| Stat | Value |
|---|---|
| Median | **24ms** |
| Average | 62ms |
| Max | 413ms |
| Min | 5ms |

All 13 under half a second; all but one under 100ms. This is
imperceptibly fast for a real conversational interruption — well within
what would feel instantaneous to a user.

### Resource usage under sustained concurrent load (142s endurance run)

- **Memory**: free pages ranged 57MB-716MB throughout (tight at times,
  consistent with `qwen2.5:32b`'s 19GB footprint + STT/TTS/VAD all
  active), but **zero new swap activity** (`Swapouts` counter unchanged
  for the entire 142s window). No thermal/pressure creep pattern
  observed — free memory fluctuated with the natural cycle of
  synthesis/playback rather than trending downward over time.
- **GPU/CPU**: not separately re-measured with `powermetrics` this story
  (avoided re-imposing the sudo/password flow on Andrey after
  `STORY-01-05`'s compute-backend-audit detour) — `STORY-01-03`
  already confirmed `qwen2.5:32b` runs at ~100% GPU via Ollama, and nothing
  in this story's observed latencies suggests new contention; a full
  `powermetrics` capture during concurrent barge-in load would be a
  reasonable follow-up if EPIC-06 implementation raises new questions.
- No crash, no OOM, no multi-second stall — consistent with the
  established pattern from `STORY-01-01`/`STORY-01-02`: `qwen2.5:32b`
  (19GB) + lightweight STT/VAD/TTS is comfortably within this 48GB
  machine's budget. This is nothing like the `llama3.3:70b` incident.

### False-positive check (Andrey's concern: outdoor/park noise)

Raised live by Andrey: he plans to use this while walking in a park,
worried the VAD will trigger on every ambient sound. Tested directly:
8s of deliberate **non-speech** noise (coughing, tapping, rustling, no
words) into the mic at the same threshold (0.5) used throughout —
**zero false triggers**. Silero VAD is trained to detect human speech
specifically, not generic sound energy, and behaved accordingly here.

**Not tested, and a genuine open risk**: nearby *human* speech (other
people talking near the phone mic outdoors). VAD detects "is there
speech-like audio," not "is this specifically the user's voice" —
without directional/beamforming hardware or speaker verification, a
phone mic can't distinguish the user's voice from a stranger's
conversation nearby. This is a real limitation of the VAD-only approach,
not something this Mac-based PoC can properly validate (no outdoor
mic environment available) — flagged explicitly for field testing once
the Android client exists (see Recommendation).

## Comparison to Andrey's prior NVIDIA real-time-model experience

Andrey's concern going in was based on prior experience with
resource-hungry NVIDIA real-time conversational models. This pipeline is
in a meaningfully different resource class: a single ~19GB LLM plus
lightweight STT (whisper.cpp, ~1.5GB)/VAD (silero, tiny)/TTS (Piper,
CPU-only, tiny) — not a multi-model GPU-cluster setup. The 142s
sustained-load test with zero swap activity and comfortable (if not
huge) memory headroom supports that this is **not** in the same danger
zone.

## Verdict: GO

Barge-in is **resource-feasible** on this hardware with the PoC's
leading candidates (`qwen2.5:32b` + `whisper.cpp` + Piper). Stop latency
is excellent (median 24ms). Memory/stability held up over a sustained
142s concurrent-load session with zero swap growth.

**One caveat attached to the GO, not blocking it**: the
nearby-human-speech false-positive risk (above) is unresolved and can't
be fully tested until there's a real Android client in a real outdoor
environment. Recommend EPIC-06 budget a field-testing pass specifically
for this before considering barge-in "done," and consider a fallback
design (e.g. a brief confirmation window, or a physical
push-to-talk-to-interrupt option) if false triggers turn out to be a
real problem in the park.

## Recommendation

1. **Proceed with `EPIC-06` (barge-in)** — scheduled, not descoped.
2. **Carry forward**: VAD threshold 0.5, chunk size 512 samples (32ms),
   `VADIterator`'s built-in `min_silence_duration_ms`/`speech_pad_ms`
   defaults all worked well here: reuse as the starting point for the
   real implementation rather than re-deriving from scratch.
3. **New follow-up for EPIC-06 design**: the client-side LLM stream
   wasn't explicitly cancelled server-side on interrupt in this spike
   (breaking the Python iterator stops *consuming* the stream but
   doesn't guarantee Ollama stops *generating*) — the real
   implementation needs an explicit cancellation call, not just
   client-side silence, to actually free compute on interrupt.
4. **New follow-up for EPIC-06 design**: budget a field test for the
   nearby-human-speech false-positive risk once the Android client
   exists, per the caveat above.
