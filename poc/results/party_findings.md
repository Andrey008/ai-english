# Party-mode spike (2026-11-17) — one LLM call voicing two characters

Script: `poc/party_spike.py` (scripted 21-turn runs + `--chat` interactive).
Model: gemma2:27b. Transcripts: `poc/results/party_transcripts/` (`v1/` = first prompt).

## Approach
One generation per user turn, lines tagged `[NAME] ...`, parsed on the fly
(each segment -> its own TTS voice). Code caps at 2 lines and drops a
trailing non-question line after a question line.

## Results (84 turns, 2 scenarios x 2 prompt versions)
| | v1 interview | v1 pub | v2 interview | v2 pub |
|---|---|---|---|---|
| Parseable / known tags / English | 100% | 100% | 100% | 100% |
| Named person answers first | 6/6 | 3/3 | 6/6 | 3/3 |
| Ends handing floor to user | 4/21 | 12/21 | 17/21 (4 legit: repeat-question, goodbye) | 21/21 |
| Lines per turn (1 / 2) | 1 / 20 | 0 / 21 | 18 / 3 | 1 / 20 |
| LLM first speakable sentence, median | 1.86s | 1.37s | 1.65s | 1.46s |
| TTFT median | 0.81s | 0.79s | 0.78s | 0.81s |
First turn ~4.7s every run = cold prefill of the new system prompt (the
existing prewarm would cover it).

## Verdict: GO on mechanics
Format, addressing, language and latency are solved. The v2 prompt rule
"reaction first, question to the user LAST" fixed the main v1 failure
(second speaker burying the first one's question with filler).

## Open quality issues (prompt / scenario work, not blockers)
- Interview: interviewers rarely follow up on the actual answer; topics
  jump; pacing rushes to the close by ~turn 13; "Can I ask both of you"
  answered by only one. Likely better with EPIC-10's server-driven
  question flow than with free prompting.
- Pub: lively and clearly distinct characters, but almost always 2 lines
  per turn despite the prompt -> more listening per turn. Acceptable for
  casual; may need a code-side probability cap if it feels like too much.
- Not tested: real voice/TTS switching between segments, STT names
  ("Priya" misheard), long sessions with compaction, persona memory.
