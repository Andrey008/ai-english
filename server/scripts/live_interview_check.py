"""Ad hoc live check for the `job_interview_basic` scenario (STORY-03-05),
reusing `live_persona_spotcheck.py`'s WS-driving machinery with
interview-appropriate scripted candidate answers."""
from __future__ import annotations

import asyncio

from live_persona_spotcheck import print_transcript, run
import live_persona_spotcheck as lps

INTERVIEW_LINES = [
    "Hey.",
    "I'm doing well, thanks -- yeah, found it fine.",
    "I just graduated with a marketing degree.",
    "I'm really drawn to brand storytelling.",
    "Sure -- I led a student campaign that increased event signups by thirty percent.",
    "I think I'd bring a lot of energy and fresh ideas.",
]

if __name__ == "__main__":
    lps.USER_LINES = INTERVIEW_LINES
    sid = asyncio.run(run("ws://127.0.0.1:8000/ws/session", None, "job_interview_basic", len(INTERVIEW_LINES)))
    print_transcript(sid)
