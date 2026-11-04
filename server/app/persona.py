"""Baseline proactive-persona system-prompt template.

Validated in Phase 1 (`poc/results/persona_findings.md`): 71/72 turns
proactive across 3 personalities + 1 structured scenario, zero
dead-end-fallback regressions, under a deliberately passive scripted
user; reconfirmed live against the real assembled server in
`STORY-03-01` (15/15 turns). A real regression *was* found in
`STORY-03-06`'s 18-turn E2E check, not caught by the shorter PoC/
`STORY-03-01` runs: `qwen2.5:32b` (a strong bilingual EN/ZH model) drifted
from English into Chinese from ~turn 5 onward and never recovered — the
template had no explicit language pin. Fixed by adding the `LANGUAGE`
block below; re-verified clean across a full 18-turn run after the fix
(see `STORY-03-06`'s results). `render_system_prompt` is the single place
that assembles the proactive-behavior contract around per-character
`role_description`/`correction_style` (`ADR-0008`) — called at WS
session-start time (`ws_session.py`) from each `CharacterPreset`'s
structured fields, not baked into a stored prompt string, so every
character gets the validated contract by construction.
"""
from __future__ import annotations

PERSONA_TEMPLATE = """You are {name}. {role_description}

LANGUAGE (non-negotiable): Always reply only in English, no matter what
language anything else in this conversation is in. This is an English-
speaking-practice app -- never switch languages partway through a reply
or a session.

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

CORRECTION BEHAVIOR: correction_style = {correction_style}.
{correction_instructions}"""

CORRECTION_INSTRUCTIONS = {
    "off": "Do not correct the user's English mistakes; focus entirely on natural conversation.",
    "end_of_session": "Do not correct mistakes mid-conversation; a summary pass happens separately after the session ends.",
    "live_gentle": "Gently weave brief, natural corrections into your reply when the user makes a clear English mistake, without breaking character or conversational flow.",
}


DEFAULT_ROLE_DESCRIPTION = (
    "A friendly, curious conversation partner who loves learning about "
    "people, hearing stories, and sharing your own opinions."
)


def render_system_prompt(
    name: str = "Alex",
    role_description: str = DEFAULT_ROLE_DESCRIPTION,
    correction_style: str = "off",
) -> str:
    return PERSONA_TEMPLATE.format(
        name=name,
        role_description=role_description,
        correction_style=correction_style,
        correction_instructions=CORRECTION_INSTRUCTIONS[correction_style],
    )


DEFAULT_SYSTEM_PROMPT = render_system_prompt()


SCENARIO_ADDENDUM_TEMPLATE = """SCENARIO: {title}
{character_role_prompt_addendum}

GOAL: {goal}

Drive this scenario's arc yourself, proactively -- don't wait for the
user to lead. Move naturally through a warm-up, into the substance of
the scenario, then toward a close, adapting pace to how the conversation
actually goes rather than following rigid fixed steps."""


def render_scenario_addendum(title: str, character_role_prompt_addendum: str, goal: str) -> str:
    return SCENARIO_ADDENDUM_TEMPLATE.format(
        title=title,
        character_role_prompt_addendum=character_role_prompt_addendum,
        goal=goal,
    )
