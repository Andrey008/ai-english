---
story: STORY-01-06
status: complete
updated: 2026-09-03
---

# STORY-01-06 — Proactive-persona prompt-engineering spike: findings

## Setup

Model: `qwen2.5:32b` (winning candidate from `STORY-01-03`).

Built on the draft system prompt from `STORY-01-03`'s quick
`persona_probe.py` check, refined into the baseline template (see
below) with an explicit structure: personality/role, a **proactive
behavior contract** naming the exact anti-pattern PRD §6.1 calls out
("What would you like to talk about?"), and a `correction_style`
boundary (this run used `off` — correction behavior is orthogonal to
conversational-quality testing, not in scope here).

**4 conversations, scripted deliberately-passive "user" turns** (short,
vague, one-word answers — designed to stress-test whether the model
keeps initiating or falls back to waiting on the user):
- 3 freeform personalities × 18 turns: `jamie_casual_friend` (warm close
  friend), `zara_quirky_traveler` (energetic world traveler), 
  `dr_bennett_mentor` (professional career mentor)
- 1 structured scenario × 12 turns: `scenario_job_interview`
  (`job_interview_basic` from `ARCHITECTURE.md` §3.3), interviewer
  persona driving the interview arc

Scripted (not LLM-simulated) user turns were used deliberately — this
keeps the stress test reproducible and isolates the persona model's
behavior from a second LLM's unpredictable simulated-user variance.

Full transcripts: `poc/results/persona_transcripts/*.md` +
`persona_all_transcripts.json`.

## Baseline proactive-persona system-prompt template

```
You are {name}. {role_description}

PROACTIVE BEHAVIOR CONTRACT (most important rule):
- You always drive the conversation forward. Never give a dead-end reply
  like "What would you like to talk about?" or "What do you want to talk
  about?" -- if the user gives a short, vague, or passive answer, YOU
  pick the next topic yourself and ask a specific, genuine follow-up
  question tied to something already said.
- Express real opinions and reactions, don't just interview the user.
- Stay fully in character as {name} at all times, even if the user is
  passive, bored-sounding, or gives one-word answers.
- Keep replies short and conversational (1-3 sentences), like real
  spoken dialogue -- not an essay, not a bulleted list.

CORRECTION BEHAVIOR: correction_style = {off | end_of_session | live_gentle}.
{correction-style-specific instructions}
```

For structured scenarios, an additional `SCENARIO:` block names the
scenario id, tells the character to drive the arc itself (not wait for
the user to prompt the next question), and sketches the expected shape
(warm-up → substance → close).

## Results

**Regression check (automated, regex over every reply)**: 0 hits across
all 72 assistant turns for any of: "what would/do you want to talk
about", generic "as an AI"/"as a language model" phrasing, or
similar dead-end fallbacks explicitly named in PRD §6.1.

**Proactivity signal (question/next-topic presence per turn)**: **71/72
turns (98.6%)** contained a question or explicit next-topic offer. The
one exception (`dr_bennett_mentor`, turn 15 — encouragement without a
question) was immediately followed by a normal proactive turn 16, not
the start of a decline.

**No regression over session length**: reviewed turn-by-turn across all
4 transcripts (18-turn freeform, 12-turn scenario) — no decline in
proactivity or specificity late in any conversation. If anything, the
freeform personalities got *more* inventive under sustained passive
user input (e.g. `zara_quirky_traveler` improvising an entire imaginary
street-festival scenario by turns 11-18 rather than running out of
ideas). No mitigation (periodic system-prompt reinforcement,
summarization) was needed — the story's task 5 ("try a mitigation if
regression appears") did not apply.

**Structured scenario**: `scenario_job_interview` correctly drove the
interview arc itself (background → motivation → behavioral question →
skills → close) across all 12 turns without waiting on the candidate to
lead, including handling short/uncertain candidate answers by moving
the interview forward gracefully rather than stalling.

**In-character consistency**: each personality maintained a distinct,
consistent voice throughout (Jamie casual, Zara energetic/quirky with
recurring travel-photographer flavor, Dr. Bennett measured/professional,
Ms. Chen — the interviewer — appropriately formal) — no drift toward a
generic assistant register in any transcript.

## Verdict

**`qwen2.5:32b` with this baseline system prompt reliably sustains
proactive behavior** per PRD §6.1's requirements, across 3 distinct
personalities and one structured scenario, under an adversarial
(deliberately passive) user, for sessions well beyond a
first-impression length (18 turns). This is a strong result — no
regression pattern was found, so no mitigation needed to be tested.

## Recommendation

- **Carry the baseline template above into EPIC-03** (character
  preset system) as the default proactive-behavior contract every
  character's system prompt should include, with per-character
  `role_description` and `correction_style` slotted in.
- **Caveat, honestly stated**: this used scripted passive user turns,
  not a real live conversation with Andrey. It's a strong controlled
  stress test, but a live spot-check (even a short one) before EPIC-03
  locks in the template would still be worth doing — scripted turns
  can't fully replicate real conversational dynamics (interruptions,
  genuinely surprising user input, actual accent/speech patterns
  feeding back through the full pipeline).
- **Learning-layer correction styles were not tested here** (`off` only)
  — `end_of_session` and `live_gentle` correction behavior should get
  their own check when EPIC-04 (learning layer) is detailed, since
  `live_gentle` in particular has real potential to conflict with the
  proactive-behavior contract (correcting *and* staying in-character
  *and* driving the conversation forward, all at once) — flagged as an
  open question for that epic's planning, not resolved here.
