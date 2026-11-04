"""STORY-01-03 helper: lightweight quality/persona check for the LLM
candidates. Not the full STORY-01-06 spike (that does 15-20 turns across
3 personalities) -- this is a short (~8 turn) scripted conversation per
candidate model, using a draft proactive-persona system prompt, to catch
any model that regresses to generic-assistant tone or refuses to drive
the conversation. Transcripts are saved for STORY-01-06 to reuse/extend.
"""
import json
import sys

import ollama

MODELS = ["qwen2.5:32b", "gemma2:27b"]

# Draft only -- STORY-01-06 owns the real system-prompt design.
DRAFT_PERSONA_PROMPT = """\
You are Alex, a friendly, curious conversation partner helping the user \
practice spoken English. You are NOT a generic assistant: you have your \
own opinions, you ask follow-up questions, and you actively drive the \
conversation forward rather than waiting passively for the user to lead. \
Stay in character as Alex at all times. Keep replies short and \
conversational (1-3 sentences), like real spoken dialogue, not an essay. \
If the user makes a language mistake, do not correct them unless it \
blocks understanding -- prioritize a natural, engaging conversation over \
being a strict teacher.
"""

# Scripted "user" turns simulating a non-native speaker in a free-form
# chat, written to plausibly test proactivity (short/passive replies that
# a generic assistant might respond to by going flat and just waiting).
SCRIPTED_USER_TURNS = [
    "Hi! I want to practice my English today.",
    "Not much, just a normal day at work.",
    "Yeah it was okay I guess.",
    "Hmm, I don't know, what do you want to talk about?",
    "I like watching movies sometimes.",
    "Action movies, I think. Also some comedy.",
    "What about you, do you like movies?",
    "That's cool. Okay what else can we talk about?",
]


def run_conversation(model: str) -> list[dict]:
    messages = [{"role": "system", "content": DRAFT_PERSONA_PROMPT}]
    transcript = []
    for user_turn in SCRIPTED_USER_TURNS:
        messages.append({"role": "user", "content": user_turn})
        resp = ollama.chat(model=model, messages=messages)
        reply = resp["message"]["content"].strip()
        messages.append({"role": "assistant", "content": reply})
        transcript.append({"user": user_turn, "assistant": reply})
        print(f"USER: {user_turn}\nALEX: {reply}\n")
    return transcript


def save_transcript_md(model: str, transcript: list[dict]):
    safe_name = model.replace(":", "_").replace("/", "_")
    path = f"results/persona_transcripts_draft/{safe_name}.md"
    with open(path, "w") as f:
        f.write(f"# Draft persona-quality probe -- {model}\n\n")
        f.write("STORY-01-03 quick check (not the full STORY-01-06 spike).\n\n")
        for turn in transcript:
            f.write(f"**User:** {turn['user']}\n\n**Alex:** {turn['assistant']}\n\n")
    print(f"Written to {path}")


if __name__ == "__main__":
    models = [sys.argv[1]] if len(sys.argv) > 1 else MODELS
    for model in models:
        print(f"\n=== {model} ===")
        transcript = run_conversation(model)
        save_transcript_md(model, transcript)
        safe_name = model.replace(":", "_").replace("/", "_")
        with open(f"results/persona_transcripts_draft/{safe_name}.json", "w") as f:
            json.dump(transcript, f, indent=2)
