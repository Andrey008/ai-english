"""Interview state machine (STORY-10-03, ADR-0016 §2).

The server — not the LLM — owns the question order. For every user turn
`plan_turn` decides what happens:

- a voice command (skip / repeat), or an answer with no follow-up left →
  a scripted reply ("Okay, thanks." + the next question), no LLM;
- otherwise (follow-up allowed, or rephrase) → an LLM reply guided by a
  short note, and `finish_reply` then decides, from what the model
  actually said, whether the server appends the next question verbatim.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.interview import prompts

# "s?kip": whisper turned a synthetic "Skip this one." into "Kip this
# one." (2026-11-13 live check).
# Commands are only recognised in short utterances, so a real answer
# that happens to contain "move on" or "repeat" is never mistaken for one.
COMMAND_MAX_WORDS = 8
_REPEAT = re.compile(
    r"\b(repeat( the question| that| it)?|say (that|it) again|one more time|pardon|"
    r"what was the question|sorry,? what)\b", re.I)
_REPHRASE = re.compile(
    r"\b(rephrase|what do you mean|(i )?(don'?t|do not) understand( the question)?|"
    r"in other words|(say|ask) it (more )?simpl(y|er))\b", re.I)
_SKIP = re.compile(
    r"\b(s?kip( it| this( one| question)?)?|next question|(let'?s )?move on|i'?ll pass)\b", re.I)


# A follow-up isn't always a question mark: gemma said "Tell me more
# about your experience with Java microservices." (2026-11-13), and the
# next question was appended right after it. So only a short line with
# no request in it counts as a plain acknowledgement.
ACK_MAX_WORDS = 10
_REQUEST = re.compile(
    r"\b(tell me|walk me|describe|explain|elaborate|expand on|give me|share|talk (me )?(through|about)|"
    r"can you|could you|would you|what|why|how|which|when|where)\b", re.I)


def is_followup(reply: str) -> bool:
    text = reply.strip()
    return "?" in text or len(text.split()) > ACK_MAX_WORDS or bool(_REQUEST.search(text))


def detect_command(transcript: str) -> str | None:
    text = transcript.strip()
    if not text or len(text.split()) > COMMAND_MAX_WORDS:
        return None
    if _REPEAT.search(text):
        return "repeat"
    if _REPHRASE.search(text):
        return "rephrase"
    if _SKIP.search(text):
        return "skip"
    return None


@dataclass
class InterviewItem:
    idx: int
    question_id: str
    category: str
    question_ru: str
    question_en: str
    status: str = "pending"   # pending | asked | answered | skipped

    def as_row(self) -> dict:
        return dict(idx=self.idx, question_id=self.question_id, category=self.category,
                    question_ru=self.question_ru, question_en=self.question_en, status=self.status)


@dataclass
class TurnPlan:
    kind: str                       # "scripted" | "llm"
    question_idx: int               # the question the user's turn belongs to
    command: str | None = None
    scripted_text: str | None = None
    llm_text: str | None = None     # transcript + note (what the LLM sees)
    followup_allowed: bool = False


@dataclass
class InterviewState:
    name: str
    items: list[InterviewItem]
    max_followups: int = 1
    index: int = 0
    followups_used: int = 0
    finished: bool = False
    changed: list[int] = field(default_factory=list)   # item idx whose status changed, for the DB
    _ack_turn: int = 0

    @property
    def count(self) -> int:
        return len(self.items)

    @property
    def current(self) -> InterviewItem:
        return self.items[self.index]

    # ---- start / resume ------------------------------------------------

    def opening(self) -> str:
        self._mark(self.index, "asked")
        return prompts.opening_line(self.name, self.count, self.current.question_en)

    @classmethod
    def resumed(cls, name: str, items: list[InterviewItem], max_followups: int) -> "InterviewState":
        state = cls(name=name, items=items, max_followups=max_followups)
        open_items = [i for i in items if i.status in ("pending", "asked")]
        if not open_items:
            state.index = len(items) - 1
            state.finished = True
        else:
            state.index = open_items[0].idx
        return state

    def resume_line(self) -> str:
        if self.finished:
            return prompts.ALREADY_DONE_LINE
        self._mark(self.index, "asked")
        return prompts.resume_line(self.index + 1, self.current.question_en)

    # ---- turns ---------------------------------------------------------

    def plan_turn(self, transcript: str) -> TurnPlan:
        idx = self.index
        command = detect_command(transcript)
        if command == "repeat":
            return TurnPlan("scripted", idx, command, scripted_text=self.current.question_en)
        if command == "skip":
            self._mark(idx, "skipped")
            return TurnPlan("scripted", idx, command, scripted_text=f"{prompts.SKIP_LINE} {self._advance()}")
        if command == "rephrase":
            note = prompts.REPHRASE_NOTE
            return TurnPlan("llm", idx, command, llm_text=f"{transcript}\n\n{note}")
        if self.followups_used < self.max_followups:
            note = prompts.FOLLOWUP_NOTE
            return TurnPlan("llm", idx, llm_text=f"{transcript}\n\n{note}", followup_allowed=True)
        # No follow-up left: the reply is just "okay" + the next question.
        # Scripted, not the LLM — told to only acknowledge, gemma still
        # invented a question of its own now and then (2026-11-13), and
        # this way the turn has no LLM latency at all.
        self._mark(idx, "answered")
        ack = prompts.ACKS[self._ack_turn % len(prompts.ACKS)]
        self._ack_turn += 1
        return TurnPlan("scripted", idx, scripted_text=f"{ack} {self._advance()}")

    def finish_reply(self, plan: TurnPlan, reply: str) -> str | None:
        """Called with the model's full reply; returns text the server
        speaks right after it (the next question / the closing), or None
        when the model asked a follow-up (or rephrased) and we wait."""
        if plan.command == "rephrase":
            return None
        if plan.followup_allowed and is_followup(reply):
            self.followups_used += 1
            return None
        self._mark(plan.question_idx, "answered")
        return self._advance()

    # ---- internals -----------------------------------------------------

    def _advance(self) -> str:
        self.followups_used = 0
        if self.index >= self.count - 1:
            self.finished = True
            return prompts.CLOSING_LINE
        self.index += 1
        self._mark(self.index, "asked")
        return prompts.next_question_line(self.index + 1, self.count, self.current.question_en)

    def _mark(self, idx: int, status: str) -> None:
        item = self.items[idx]
        if item.status != status and not (item.status in ("answered", "skipped") and status == "asked"):
            item.status = status
            self.changed.append(idx)

    def take_changes(self) -> list[InterviewItem]:
        changed, self.changed = self.changed, []
        return [self.items[i] for i in dict.fromkeys(changed)]
