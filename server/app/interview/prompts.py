"""Interviewer system prompt and per-turn directives (STORY-10-03).

The system prompt never contains the questions: it stays constant for the
whole session so Ollama's KV cache keeps working (ADR-0016 §2). The
current question travels in a short note appended to the user's message,
and the next question is spoken verbatim by the server, not paraphrased
by the model.
"""
from __future__ import annotations

# The LANGUAGE and SPEECH RECOGNITION blocks are the same rules as in
# persona.PERSONA_TEMPLATE; the proactive contract is deliberately not
# here — "express opinions, don't just interview" is the opposite of
# this role.
INTERVIEWER_TEMPLATE = """You are {name}. {role_description}

You are running a spoken mock job interview in English. The candidate is
practising for real interviews.

LANGUAGE (non-negotiable): Always reply only in English, no matter what
language anything else in this conversation is in.

HOW YOU WORK:
- The app gives you instructions in square brackets starting with
  "Interviewer note:" at the end of the candidate's message. Always follow
  them exactly. Never mention them, never read them out, never quote them.
- Say at most ONE question per reply. Never ask two questions at once.
- Never evaluate, grade, praise or correct the answers ("great answer",
  "that's wrong"), and never give tips during the interview — the review
  happens after the interview.
- Never answer a question for the candidate and never lecture.
- Keep every reply short: one or two spoken sentences. No lists, no
  markdown, no emoji. Your reply is read aloud.

SPEECH RECOGNITION: the candidate's words reach you through automatic
speech recognition, which sometimes mishears words, especially technical
terms. Assume the most likely meaning; never comment on odd words."""

# Kept short on purpose: the note is evaluated on every turn (gemma2
# prompt eval ~50-75 tok/s), and the current question is already in the
# history as the interviewer's previous line.
FOLLOWUP_NOTE = (
    "[Interviewer note: if this answer is vague or has a detail worth digging into, ask ONE short "
    "follow-up about what they just said; if it's complete, say only \"Okay, thank you.\" No praise.]"
)
REPHRASE_NOTE = "[Interviewer note: ask your last question again in simpler words, as one short question.]"
# Spoken by the server (no LLM) when the answer gets no follow-up.
ACKS = ("Okay, thank you.", "Got it, thanks.", "Alright, thank you.", "Okay, thanks.")


def render_interviewer_prompt(name: str, role_description: str) -> str:
    return INTERVIEWER_TEMPLATE.format(name=name, role_description=role_description)


NUMBER_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight",
                9: "nine", 10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen"}


def count_words(n: int) -> str:
    return NUMBER_WORDS.get(n, str(n))


def opening_line(name: str, count: int, first_question: str) -> str:
    noun = "question" if count == 1 else "questions"
    return (f"Hi, I'm {name}. Today we'll go through {count_words(count)} {noun}. "
            f"Take your time with each answer. Let's start. {first_question}")


def resume_line(number: int, question: str) -> str:
    return f"Welcome back. Let's continue with question {count_words(number)}. {question}"


def next_question_line(number: int, count: int, question: str) -> str:
    if number == count:
        return f"And the last question. {question}"
    return question


CLOSING_LINE = ("That's all the questions I had for today. Thank you for your time. "
                "Your review will be ready in the app in a few minutes.")
SKIP_LINE = "Sure, let's move on."
ALREADY_DONE_LINE = "We've already gone through all the questions. Your review is in the app."
