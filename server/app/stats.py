"""Practice stats: how much the user talked, from the `turns` table.

Two kinds of time:
- speaking / listening: the audio of the user's turns (VAD utterance) and
  of the character's turns (TTS), from `turns.audio_ms`. Turns recorded
  before that column existed get an estimate from their word count, and
  the estimated part is reported separately.
- practice: active conversation time. Turns are a timeline; the time
  between two consecutive turns counts, but idle time in it (nobody
  speaking) is capped at `idle_cap_s` — so an app left open, or a
  conversation resumed days later, adds at most that much. The wall-clock
  `ended_at - started_at` of a session is not used: a resumed session keeps
  its original `started_at` (ADR-0015).

Days are local days in the given timezone. Pure functions — no DB, no
app state — so this is tested on plain rows.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo
from typing import Any, Callable, Iterable

# Word-count estimates for turns without audio_ms: a learner speaks
# slower (~120 wpm, VAD padding included) than the TTS voice (~150 wpm).
USER_WORDS_PER_S = 2.0
ASSISTANT_WORDS_PER_S = 2.5
DEFAULT_IDLE_CAP_S = 90.0
# Below this much measured speech a words-per-minute figure is noise.
MIN_WPM_SPEECH_S = 60.0


@dataclass
class _Acc:
    sessions: set = field(default_factory=set)
    user_turns: int = 0
    user_words: int = 0
    practice_s: float = 0.0
    speaking_s: float = 0.0
    listening_s: float = 0.0
    estimated_s: float = 0.0  # estimated part of speaking_s + listening_s
    measured_words: int = 0
    measured_speaking_s: float = 0.0

    def add(self, other: "_Acc") -> None:
        self.sessions |= other.sessions
        for name in ("user_turns", "user_words", "practice_s", "speaking_s", "listening_s",
                     "estimated_s", "measured_words", "measured_speaking_s"):
            setattr(self, name, getattr(self, name) + getattr(other, name))

    def as_dict(self) -> dict:
        wpm = None
        if self.measured_speaking_s >= MIN_WPM_SPEECH_S:
            wpm = round(self.measured_words / (self.measured_speaking_s / 60), 1)
        return {
            "sessions": len(self.sessions),
            "user_turns": self.user_turns,
            "user_words": self.user_words,
            "practice_s": round(self.practice_s),
            "speaking_s": round(self.speaking_s),
            "listening_s": round(self.listening_s),
            "estimated_audio_s": round(self.estimated_s),
            "avg_words_per_turn": round(self.user_words / self.user_turns, 1) if self.user_turns else None,
            "words_per_minute": wpm,
        }


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _audio_s(turn: dict) -> tuple[float, bool]:
    """(seconds of audio, whether it is an estimate)."""
    if turn.get("audio_ms") is not None:
        return turn["audio_ms"] / 1000, False
    words = len(turn["text"].split())
    rate = USER_WORDS_PER_S if turn["role"] == "user" else ASSISTANT_WORDS_PER_S
    return words / rate, True


def _kind(character_id: str | None, scenario_id: str | None, is_interview: Callable[[str | None], bool]) -> str:
    if is_interview(character_id):
        return "interview"
    return "scenario" if scenario_id else "free"


def compute_stats(
    turns: Iterable[dict],
    *,
    now: datetime,
    tz: tzinfo,
    days: int = 30,
    idle_cap_s: float = DEFAULT_IDLE_CAP_S,
    character_name: Callable[[str | None], str | None] = lambda _id: None,
    is_interview: Callable[[str | None], bool] = lambda _id: False,
) -> dict[str, Any]:
    """`turns`: rows of `Database.stats_turns` (session_id, role, text, ts,
    audio_ms, character_id, scenario_id), ordered by session then ts."""
    by_day: dict[date, _Acc] = defaultdict(_Acc)
    by_character: dict[str | None, _Acc] = defaultdict(_Acc)
    by_kind: dict[str, _Acc] = defaultdict(_Acc)

    prev: dict | None = None
    prev_audio = 0.0
    for turn in turns:
        at = _parse_ts(turn["ts"])
        day = at.astimezone(tz).date()
        audio, estimated = _audio_s(turn)
        same_session = prev is not None and prev["session_id"] == turn["session_id"]
        if same_session:
            gap = max(0.0, (at - _parse_ts(prev["ts"])).total_seconds())
            # The gap holds the rest of the previous reply's playback (TTS
            # is sent faster than real time), thinking, and this turn's
            # speech; only the silence beyond the audio is capped.
            carry = prev_audio if prev["role"] == "assistant" else 0.0
            practice = min(gap, audio + carry + idle_cap_s)
        else:
            if prev is not None and prev["role"] == "assistant":
                _credit_tail(prev, prev_audio, tz, by_day, by_character, by_kind, is_interview)
            practice = audio

        acc = _Acc(practice_s=practice)
        if turn["role"] == "user":
            words = len(turn["text"].split())
            acc.sessions.add(turn["session_id"])
            acc.user_turns = 1
            acc.user_words = words
            acc.speaking_s = audio
            if not estimated:
                acc.measured_words = words
                acc.measured_speaking_s = audio
        else:
            acc.listening_s = audio
        if estimated:
            acc.estimated_s = audio
        _credit(acc, day, turn, by_day, by_character, by_kind, is_interview)
        prev, prev_audio = turn, audio
    if prev is not None and prev["role"] == "assistant":
        _credit_tail(prev, prev_audio, tz, by_day, by_character, by_kind, is_interview)

    today = now.astimezone(tz).date()
    totals, today_acc, week, month = _Acc(), _Acc(), _Acc(), _Acc()
    for day, acc in by_day.items():
        totals.add(acc)
        age = (today - day).days
        if age == 0:
            today_acc.add(acc)
        if 0 <= age < 7:
            week.add(acc)
        if 0 <= age < 30:
            month.add(acc)

    daily = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        acc = by_day.get(day, _Acc())
        daily.append({
            "date": day.isoformat(),
            "practice_s": round(acc.practice_s),
            "speaking_s": round(acc.speaking_s),
            "user_words": acc.user_words,
            "sessions": len(acc.sessions),
        })

    characters = [
        {"character_id": cid, "name": character_name(cid), **acc.as_dict()}
        for cid, acc in by_character.items()
    ]
    characters.sort(key=lambda c: c["practice_s"], reverse=True)

    practiced_days = {day for day, acc in by_day.items() if acc.user_turns}
    return {
        "timezone": str(tz),
        "generated_at": now.isoformat(),
        "first_day": min(practiced_days).isoformat() if practiced_days else None,
        "totals": totals.as_dict(),
        "today": today_acc.as_dict(),
        "last_7_days": week.as_dict(),
        "last_30_days": month.as_dict(),
        "streak": _streak(practiced_days, today),
        "daily": daily,
        "by_character": characters,
        "by_kind": {kind: by_kind[kind].as_dict() for kind in ("free", "scenario", "interview")},
    }


def _credit(acc, day, turn, by_day, by_character, by_kind, is_interview) -> None:
    by_day[day].add(acc)
    by_character[turn["character_id"]].add(acc)
    by_kind[_kind(turn["character_id"], turn["scenario_id"], is_interview)].add(acc)


def _credit_tail(last, last_audio, tz, by_day, by_character, by_kind, is_interview) -> None:
    """A session's last reply is still being played after its turn was
    stored; the gap that would normally count it never comes."""
    day = _parse_ts(last["ts"]).astimezone(tz).date()
    _credit(_Acc(practice_s=last_audio), day, last, by_day, by_character, by_kind, is_interview)


def _streak(days: set[date], today: date) -> dict:
    """Consecutive practiced days ending today — or yesterday, so the
    streak isn't shown as lost before today's practice."""
    longest = run = 0
    previous = None
    for day in sorted(days):
        run = run + 1 if previous is not None and (day - previous).days == 1 else 1
        longest = max(longest, run)
        previous = day
    current = 0
    cursor = today if today in days else today - timedelta(days=1)
    while cursor in days:
        current += 1
        cursor -= timedelta(days=1)
    return {"current_days": current, "longest_days": longest, "practiced_today": today in days}
