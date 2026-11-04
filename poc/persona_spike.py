"""STORY-01-06: proactive-persona prompt-engineering spike.

Tests the baseline proactive-persona system prompt across 3 freeform
personalities (>=18 turns each) + 1 structured scenario (job interview),
using scripted, deliberately passive "user" turns to stress-test whether
the model keeps driving the conversation or regresses to generic
dead-end fallbacks (PRD Sec6.1) as the session gets long.
"""
import json
import os
import re

import ollama

MODEL = "qwen2.5:32b"  # winning candidate from STORY-01-03

# --- Baseline proactive-persona template ------------------------------
# Structure: personality/role, proactive-behavior contract, correction
# boundary rules (per ARCHITECTURE.md correction_style: off | end_of_session
# | live_gentle). This run uses "off" for all personalities (the
# conversational-quality question is orthogonal to correction behavior;
# STORY-01-06 doesn't need to also test the learning layer).

def build_system_prompt(name: str, role_description: str, extra: str = "") -> str:
    return f"""\
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

CORRECTION BEHAVIOR: correction_style = off. Do not correct grammar or
word choice. Focus entirely on being an engaging conversational partner.
{extra}"""

PERSONALITIES = {
    "jamie_casual_friend": build_system_prompt(
        "Jamie",
        "A laid-back, warm close friend the user has known for years. "
        "You text/talk like a real friend -- casual, curious about their "
        "life, a little teasing sometimes, genuinely interested.",
    ),
    "zara_quirky_traveler": build_system_prompt(
        "Zara",
        "An energetic, quirky world traveler and street photographer who "
        "has lived in 6 countries. You have strong, funny opinions about "
        "food, cities, and weird travel stories, and you love pulling "
        "the user into your enthusiasm.",
    ),
    "dr_bennett_mentor": build_system_prompt(
        "Dr. Bennett",
        "A warm but professional career mentor figure, a bit formal but "
        "not stiff. You ask thoughtful questions about the user's work "
        "and goals and share your own perspective from years of "
        "experience.",
    ),
}

INTERVIEW_SCENARIO_PROMPT = build_system_prompt(
    "Ms. Chen",
    "A friendly but professional job interviewer conducting a warm-up "
    "interview for an entry-level marketing role.",
    extra=(
        "\nSCENARIO: You are running a structured job-interview practice "
        "session (scenario: job_interview_basic). YOU drive the "
        "interview -- ask the next question yourself, don't wait for the "
        "user to prompt you. Move through a natural interview arc: "
        "warm-up/small talk, background, motivation, a light behavioral "
        "question, and a closing question. Advance the scenario even if "
        "the candidate's answers are short."
    ),
)

# Deliberately passive/short scripted "user" turns -- stress-tests
# whether the model keeps initiating as the conversation gets long.
SCRIPTED_USER_TURNS = [
    "Hey.",
    "Not much, just a normal day.",
    "Yeah it was okay I guess.",
    "Hmm, I don't know, what do you want to talk about?",
    "I like watching movies sometimes.",
    "Action movies, I think. Also some comedy.",
    "What about you?",
    "That's cool. Okay what else can we talk about?",
    "I don't really know much about that.",
    "Maybe. I haven't thought about it.",
    "Sure, whatever you want to talk about.",
    "Yeah.",
    "I guess so.",
    "Hmm, hard to say.",
    "Okay.",
    "I'm not sure honestly.",
    "That's interesting I guess.",
    "Yeah maybe sometime.",
]

SCRIPTED_INTERVIEW_TURNS = [
    "Hi, thanks for having me.",
    "I'm doing well, thank you.",
    "I studied marketing at university and worked at a small agency for two years.",
    "I guess I just want a new challenge.",
    "I'm not sure, maybe better growth opportunities.",
    "I worked on a few social media campaigns.",
    "It was fine, nothing too dramatic.",
    "I'd say I'm pretty organized.",
    "Hmm, hard to think of one right now.",
    "I think I handled it okay.",
    "Sure, sounds good.",
    "No, I don't have any questions right now.",
]

REGRESSION_PATTERNS = [
    r"what (would|do) you (want|wanna) to talk about",
    r"what.{0,15}talk about",
    r"as an ai\b",
    r"as a language model",
    r"i'?m (just )?an ai\b",
    r"is there anything (else )?you'?d like to (talk about|discuss)",
]


def run_conversation(system_prompt: str, user_turns: list[str]) -> list[dict]:
    messages = [{"role": "system", "content": system_prompt}]
    transcript = []
    for i, user_turn in enumerate(user_turns):
        messages.append({"role": "user", "content": user_turn})
        resp = ollama.chat(model=MODEL, messages=messages)
        reply = resp["message"]["content"].strip()
        messages.append({"role": "assistant", "content": reply})
        flags = [p for p in REGRESSION_PATTERNS if re.search(p, reply, re.IGNORECASE)]
        has_question = "?" in reply
        transcript.append({
            "turn": i + 1,
            "user": user_turn,
            "assistant": reply,
            "has_question": has_question,
            "regression_flags": flags,
        })
        print(f"[{i+1}] USER: {user_turn}")
        print(f"[{i+1}] REPLY: {reply}" + (f"  ⚠️ {flags}" if flags else ""))
    return transcript


def save(name: str, transcript: list[dict]):
    os.makedirs("results/persona_transcripts", exist_ok=True)
    with open(f"results/persona_transcripts/{name}.json", "w") as f:
        json.dump(transcript, f, indent=2)
    with open(f"results/persona_transcripts/{name}.md", "w") as f:
        f.write(f"# Persona transcript — {name}\n\n")
        for t in transcript:
            flag_note = f"  ⚠️ **{t['regression_flags']}**" if t["regression_flags"] else ""
            f.write(f"**Turn {t['turn']} — User:** {t['user']}\n\n")
            f.write(f"**Assistant:**{flag_note} {t['assistant']}\n\n")


if __name__ == "__main__":
    all_results = {}
    for name, prompt in PERSONALITIES.items():
        print(f"\n=== {name} ===")
        transcript = run_conversation(prompt, SCRIPTED_USER_TURNS)
        save(name, transcript)
        all_results[name] = transcript

    print("\n=== job_interview_basic (structured scenario) ===")
    transcript = run_conversation(INTERVIEW_SCENARIO_PROMPT, SCRIPTED_INTERVIEW_TURNS)
    save("scenario_job_interview", transcript)
    all_results["scenario_job_interview"] = transcript

    with open("results/persona_all_transcripts.json", "w") as f:
        json.dump(all_results, f, indent=2)
    print("\nDone.")
