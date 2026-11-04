"""Text-based end-of-turn heuristic ("smart turn", STORY-05-11 follow-up).

A fixed VAD silence cutoff can't tell "I'm done" from "I'm searching for
the next word" — and language learners pause mid-sentence a lot. After
VAD reports a pause, the utterance is transcribed anyway (STT is needed
for the reply regardless), so its text is free to inspect: if it looks
unfinished, the session holds the turn open a little longer for the user
to continue instead of replying over them.

Deliberately simple and conservative — only flags endings that are
almost never a finished thought in English. An audio/prosody model
(e.g. Pipecat's Smart Turn) is the documented next step if this misfires;
see `Docs/STATUS.md` → "smart turn detection".
"""
from __future__ import annotations

import re

# whisper.cpp marks speech that trails off with an ellipsis/dash.
_TRAILING_PUNCT = ("...", "…", "-", "—", "–", ",", ";", ":")

# Words a finished English sentence practically never ends on:
# conjunctions, articles, possessives, fillers, hanging subject pronouns.
# Words that *can* close a sentence ("you", "it", "so", "about", "do",
# "too"...) are left out on purpose — a false "incomplete" only costs a
# short extra wait, but the list should still stay tight.
_DANGLING_WORDS = frozenset(
    """
    and but or because cause cuz although whereas if unless than as
    the a an my your our their its every
    to of for into onto from with at
    um uh er erm hmm
    i we they he she i'm we're they're he's she's you're
    i've we've they've i'd we'd they'd i'll we'll they'll
    very really just also even quite such
    """.split()
)

_LAST_WORD = re.compile(r"([A-Za-z']+)\W*$")


def looks_incomplete(transcript: str) -> bool:
    text = transcript.strip()
    if not text:
        return False
    if text.endswith(_TRAILING_PUNCT):
        return True
    if text.endswith(("?", "!")):
        return False
    match = _LAST_WORD.search(text)
    return bool(match) and match.group(1).lower() in _DANGLING_WORDS
