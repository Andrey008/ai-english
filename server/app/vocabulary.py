"""Vocabulary capture (AE-5): words the user didn't understand, collected
for learning elsewhere (the user copies them into EnglishDom by hand —
no SRS here).

Runs after a conversation ends (`ws_session._after_session`), never on
the live path. It reads one *visit* only: the turns after the session's
`vocab_scanned_until` watermark, plus the last character line before it
as context (the user may ask about it first thing after resuming). The
watermark then moves to the newest turn, so a resumed conversation's old
history is never analysed again; turns of a visit that ended without a
clean `session_end` are picked up by the next one.

Two triggers:
- the user asked about a word ("what does X mean?") — the word is then
  taken from the character's line, whose spelling is exact (the user's
  own line is STT output);
- a bookmark (WS `bookmark` frame) — anchored here to the character line
  that was playing or had just played when it was pressed.

No trigger in the visit → no LLM call. The pass reuses the warm
conversation model, like character memory.
"""
from __future__ import annotations

import difflib
import json
import logging
import re
from typing import Any

import ollama

from app.conversation_engine import split_sentences

logger = logging.getLogger("ai_english.vocabulary")

# Loose on purpose: a false positive only costs a little more prompt, a
# miss loses the word; the LLM and `parse_asked` sort out the rest.
RE_ASK = re.compile(
    r"\bmean(s|ing|t)?\b|\bwhat (is|are|was|were|does|do|did) (a |an |the |that |this |it )?\S+( \S+)?\s*[?.]?\s*$"
    r"|\bwhat'?s (a|an|that|this|the)\b|\bdon'?t (understand|get|know (this|that|the) word)"
    r"|\bdidn'?t (get|understand|catch)\b|\bnever heard\b|\bexplain\b|\bdefinition\b|\bnot sure what\b"
    r"|^\W*(sorry\W+|pardon\W+)?\S+( \S+)?\?\s*$",  # "sorry, crisp?"
    re.IGNORECASE,
)
# Around each trigger the LLM sees this many character lines before it and
# after it — a focused excerpt, not the whole visit: on an 86-turn
# transcript gemma2 missed a plain "What do you mean crisp?" (2026-11-20).
ASK_MAX_WORDS = 25  # longer user turns are statements ("...they don't understand the situation")
# Words of a re-ask that don't name the word asked about. Whatever is left
# ("crisp" in "What do you mean crisp?") must resemble the word found.
ASK_FILLER = set("""
a about actually again an and are ask asked by can could did didn't do does don't get got heard how i i'm is it
it's just know me mean meaning means meant mine my never not of oh ok okay please pardon question repeat
rephrase said say so sorry sure tell than that that's the this to uh um understand wanted was what what's
which with word words you you're your
""".split())
SIMILAR_MIN = 0.7  # difflib ratio, tolerant of STT misspellings ("crispy", "robast")
CONTEXT_BEFORE = 2
CONTEXT_AFTER = 1
WORD_MAX_CHARS = 60
WORD_MAX_TOKENS = 6
CONTEXT_MAX_CHARS = 240

# Two small prompts rather than one: asked together, gemma2 returned
# nothing for a bookmarked line it handled fine on its own (2026-11-20).
ASK_PROMPT = """Below are excerpts of a voice conversation between an English learner (USER, level {level}) and their English conversation partner (CHARACTER). Lines are numbered. Find the English words or expressions the USER asked the meaning of.

Include a word only if the USER asked what it means (e.g. "what does X mean?", "what is a X?", "sorry, X?", "I don't know this word") and the CHARACTER said it in an earlier line. Ignore ordinary questions ("what is your favorite food?"), topics the user asked about in general, and words the CHARACTER taught on its own ("you could say ...", "remember, X means ...") when the USER didn't ask about them. The USER's lines come from speech recognition and may be misspelled — always take the spelling from the CHARACTER's line.

For each word return:
- "word": as the CHARACTER said it (a single word may be put in its dictionary form: "reluctantly" → "reluctant"); keep phrasal verbs and idioms whole ("give up", "a piece of cake")
- "line": the number of the CHARACTER line it was said in
- "asked_in": the number of the USER line that asks about it
- "explanation": a short, simple English explanation, at most 12 words
- "translation_ru": a Russian translation, 1-4 words

Answer with JSON only: {{"words": [...]}} — {{"words": []}} if there are none.

EXCERPTS ("..." marks skipped lines):
{transcript}"""

BOOKMARK_PROMPT = """An English learner (level {level}) was listening to these lines in a conversation and pressed a button meaning "I didn't understand a word here".

For each line, pick 1 to {per_line} words or expressions from it that a {level} learner is least likely to know: rarer, more advanced or idiomatic ones, never basic words. Add a second one only if it is clearly advanced too. Keep phrasal verbs and idioms whole.

For each return:
- "word": as written in the line (a single word may be put in its dictionary form)
- "line": the number of the line
- "explanation": a short, simple English explanation, at most 12 words
- "translation_ru": a Russian translation, 1-4 words

Answer with JSON only: {{"words": [...]}}

LINES:
{lines}"""


def word_key(word: str) -> str:
    return " ".join(word.lower().split())


def is_ask(line: dict) -> bool:
    return (line["role"] == "user" and len(line["text"].split()) <= ASK_MAX_WORDS
            and bool(RE_ASK.search(line["text"])))


def asks_about(question: str, word: str) -> bool:
    """Does the user's question name this word — or no word at all ("what
    does that mean?")? Stops the model pinning some other hard word from
    the excerpt on a question about something else."""
    named = [t for t in re.findall(r"[a-z']+", question.lower()) if t not in ASK_FILLER]
    if not named:
        return True
    tokens = re.findall(r"[a-z']+", word.lower())
    return any(difflib.SequenceMatcher(None, n, t).ratio() >= SIMILAR_MIN for n in named for t in tokens)


def anchor_bookmarks(lines: list[dict], bookmarks: list[str]) -> set[int]:
    """Index (in `lines`) of the character line each bookmark refers to.

    A reply is saved only after it has been spoken, so a bookmark pressed
    while it plays sits between its user turn and it: that reply is the
    anchor. Otherwise (listening, or the reply's tail still draining) it's
    the last character line before the bookmark."""
    anchors: set[int] = set()
    for ts in bookmarks:
        anchor = None
        for i, line in enumerate(lines):
            if line["role"] != "assistant":
                continue
            if line["ts"] <= ts:
                anchor = i
                continue
            prev_user = next((lines[j]["ts"] for j in range(i - 1, -1, -1) if lines[j]["role"] == "user"), None)
            if prev_user is not None and prev_user <= ts:
                anchor = i  # this reply was being spoken
            break
        if anchor is not None:
            anchors.add(anchor)
    return anchors


def focus(lines: list[dict]) -> tuple[list[dict], set[int]]:
    """The excerpt the ask prompt reads: each re-ask with the character
    lines around it. Returns (lines, indices after which lines were
    skipped), relative to the excerpt."""
    keep: set[int] = set()
    for i, line in enumerate(lines):
        if not is_ask(line):
            continue
        before = [j for j in range(i - 1, -1, -1) if lines[j]["role"] == "assistant"][:CONTEXT_BEFORE]
        after = [j for j in range(i + 1, len(lines)) if lines[j]["role"] == "assistant"][:CONTEXT_AFTER]
        keep.update(range(min(before, default=i), max(after, default=i) + 1))
    order = sorted(keep)
    gaps = {n for n, (a, b) in enumerate(zip(order, order[1:])) if b != a + 1}
    return [lines[i] for i in order], gaps


def render_transcript(lines: list[dict], gaps: set[int] = frozenset()) -> str:
    out = []
    for i, line in enumerate(lines, start=1):
        who = "CHARACTER" if line["role"] == "assistant" else "USER"
        out.append(f"{i}. {who}: {_flat(line['text'])}")
        if (i - 1) in gaps:
            out.append("...")
    return "\n".join(out)


def render_lines(lines: list[dict]) -> str:
    return "\n".join(f"{i}. {_flat(line['text'])}" for i, line in enumerate(lines, start=1))


def _flat(text: str) -> str:
    return " ".join(text.split())


def _stems(word: str) -> list[str]:
    """Prefixes that tolerate inflection ("reluctant" → "reluctantly")
    without matching unrelated words ("bookmark" ≠ "book")."""
    return [t[: max(4, len(t) - 3)] for t in re.findall(r"[a-z']+", word.lower()) if len(t) >= 3]


def find_context(word: str, text: str) -> str | None:
    """The sentence of `text` the word was said in (prefix match, so
    "reluctant" finds "reluctantly"), or None."""
    stems = _stems(word)
    if not stems:
        return None
    for sentence in split_sentences(text) or [text]:
        low = sentence.lower()
        if all(s in low for s in stems):
            return _clip(sentence)
    return None


def _clip(text: str) -> str:
    text = " ".join(text.replace("*", "").split())  # the LLM's markdown emphasis
    return text if len(text) <= CONTEXT_MAX_CHARS else text[:CONTEXT_MAX_CHARS].rsplit(" ", 1)[0] + "…"


def _items(raw: str) -> list[dict]:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    items = data.get("words") if isinstance(data, dict) else data
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def _row(item: dict, context: str, source: str) -> dict | None:
    word = _flat(str(item.get("word") or "")).strip(" .,!?;:\"'*“”")
    if not word or len(word) > WORD_MAX_CHARS or len(word.split()) > WORD_MAX_TOKENS:
        return None
    return {
        "word": word,
        "word_key": word_key(word),
        "context": context,
        "explanation": _text(item.get("explanation"), 160),
        "translation_ru": _text(item.get("translation_ru"), 80),
        "source": source,
    }


def parse_asked(raw: str, lines: list[dict]) -> list[dict]:
    """Ask-prompt JSON → rows. A word must point at a real re-ask line
    (`asked_in`) and have been said by the character before it — so words
    the character taught unprompted, or invented ones, don't slip in."""
    assistant = [i for i, line in enumerate(lines) if line["role"] == "assistant"]
    out: list[dict] = []
    for item in _items(raw):
        asked_in = _index(item.get("asked_in"))
        word = str(item.get("word") or "")
        if not (0 <= asked_in < len(lines) and is_ask(lines[asked_in])
                and asks_about(lines[asked_in]["text"], word)):
            continue
        line_idx = _index(item.get("line"))
        # The stated line first, then the others before the question: the
        # model sometimes points at the question itself.
        candidates = [i for i in assistant if i < asked_in]
        order = ([line_idx] if line_idx in candidates else []) + [i for i in candidates if i != line_idx]
        context = next((c for i in order if (c := find_context(word, lines[i]["text"]))), None)
        if context and (row := _row(item, context, "asked")):
            out.append(row)
    return out


def parse_bookmarked(raw: str, lines: list[dict], per_line: int = 2) -> list[dict]:
    """Bookmark-prompt JSON → rows; `lines` are the bookmarked lines. At
    most `per_line` per line, in the model's order (it doesn't always
    keep to the limit)."""
    out: list[dict] = []
    taken = [0] * len(lines)
    for item in _items(raw):
        line_idx = _index(item.get("line"))
        order = ([line_idx] if 0 <= line_idx < len(lines) else []) + [i for i in range(len(lines)) if i != line_idx]
        word = str(item.get("word") or "")
        found = next(((i, c) for i in order if (c := find_context(word, lines[i]["text"]))), None)
        if found is None or taken[found[0]] >= per_line:
            continue
        if row := _row(item, found[1], "bookmark"):
            taken[found[0]] += 1
            out.append(row)
    return out


def merge(*groups: list[dict]) -> list[dict]:
    """One row per word; an earlier group wins (asked before bookmark)."""
    out: dict[str, dict] = {}
    for group in groups:
        for row in group:
            out.setdefault(row["word_key"], row)
    return list(out.values())


def _index(value: Any) -> int:
    """A 1-based line number from the LLM → 0-based index (-1 if invalid)."""
    try:
        return int(value) - 1
    except (TypeError, ValueError):
        return -1


def _text(value: Any, limit: int) -> str | None:
    text = " ".join(str(value or "").split())
    return text[:limit] or None


class VocabularyService:
    def __init__(self, config: dict[str, Any], db: Any):
        cfg = config.get("vocabulary") or {}
        self.enabled = bool(cfg.get("enabled", True))
        self._per_bookmark = int(cfg.get("max_words_per_bookmark", 2))
        self._model = config["llm"]["model"]
        self._keep_alive = str(config["llm"].get("keep_alive", "1h"))
        self._db = db
        self._client = ollama.AsyncClient()

    async def scan_session(self, session_id: str, english_level: str = "B1") -> list[dict] | None:
        """Analyse the visit since the watermark; returns the words saved
        (None if an LLM call failed — the watermark then stays, so the
        next visit retries these turns)."""
        _, before, turns, bookmarks = await self._db.vocab_scan_input(session_id)
        if not turns:
            return []
        lines = ([before] if before else []) + turns
        asked: list[dict] = []
        bookmarked: list[dict] = []
        if any(is_ask(t) for t in turns):
            excerpt, gaps = focus(lines)
            raw = await self._ask(session_id, ASK_PROMPT.format(
                level=english_level, transcript=render_transcript(excerpt, gaps)))
            if raw is None:
                return None
            asked = parse_asked(raw, excerpt)
        if anchors := anchor_bookmarks(lines, bookmarks):
            marked = [lines[i] for i in sorted(anchors)]
            raw = await self._ask(session_id, BOOKMARK_PROMPT.format(
                level=english_level, per_line=self._per_bookmark, lines=render_lines(marked)))
            if raw is None:
                return None
            bookmarked = parse_bookmarked(raw, marked, self._per_bookmark)
        words = merge(asked, bookmarked)
        if words:
            await self._db.upsert_vocabulary(session_id, words)
        await self._db.set_vocab_watermark(session_id, turns[-1]["ts"])
        if asked or bookmarks or any(is_ask(t) for t in turns):
            logger.info("vocabulary_scanned", extra={
                "session_id": session_id, "turns": len(turns), "bookmarks": len(bookmarks),
                "words": [w["word"] for w in words],
            })
        return words

    async def _ask(self, session_id: str, prompt: str) -> str | None:
        try:
            resp = await self._client.chat(
                model=self._model, keep_alive=self._keep_alive,
                messages=[{"role": "user", "content": prompt}],
                stream=False, think=False, format="json", options={"temperature": 0},
            )
        except (ollama.ResponseError, ConnectionError, OSError) as exc:
            logger.warning("vocabulary_scan_failed", extra={"session_id": session_id, "error": str(exc)})
            return None
        return resp["message"]["content"]
