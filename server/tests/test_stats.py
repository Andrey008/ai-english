import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.db import Database
from app.stats import compute_stats

UTC = timezone.utc
NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


def turn(session, role, text, at, audio_ms=None, character="emma", scenario=None):
    return {"session_id": session, "role": role, "text": text, "ts": at.isoformat(),
            "audio_ms": audio_ms, "character_id": character, "scenario_id": scenario}


def at(minutes, day=NOW):
    return day.replace(hour=10, minute=0) + timedelta(minutes=minutes)


def test_measured_speaking_listening_and_practice_with_idle_cap():
    t0 = at(0)
    rows = [
        turn("s", "assistant", "Hi there, how are you?", t0, audio_ms=2000),
        turn("s", "user", "fine thanks", t0 + timedelta(seconds=10), audio_ms=3000),
        turn("s", "assistant", "Great.", t0 + timedelta(seconds=13), audio_ms=1000),
        # 20 minutes of nothing, then one more line: only 90s of idle counts.
        turn("s", "user", "back again", t0 + timedelta(minutes=20), audio_ms=4000),
    ]
    stats = compute_stats(rows, now=NOW, tz=UTC)
    today = stats["today"]
    assert today["speaking_s"] == 7
    assert today["listening_s"] == 3
    assert today["estimated_audio_s"] == 0
    assert today["user_turns"] == 2 and today["user_words"] == 4 and today["sessions"] == 1
    # 2 (opening) + 10 + 3 + min(1187, 4 + 1 + 90) = 110
    assert today["practice_s"] == 110
    assert stats["totals"] == today


def test_old_turns_are_estimated_from_words():
    rows = [turn("s", "user", "one two three four", at(0)),
            turn("s", "assistant", "five six seven eight nine", at(0) + timedelta(seconds=5))]
    today = compute_stats(rows, now=NOW, tz=UTC)["today"]
    assert today["speaking_s"] == 2  # 4 words / 2.0
    assert today["listening_s"] == 2  # 5 words / 2.5
    assert today["estimated_audio_s"] == 4
    assert today["words_per_minute"] is None  # nothing measured


def test_last_reply_playback_counts_once_per_session():
    rows = [turn("a", "user", "hello", at(0), audio_ms=1000),
            turn("a", "assistant", "reply", at(0) + timedelta(seconds=2), audio_ms=8000),
            turn("b", "user", "hello", at(60), audio_ms=1000)]
    # a: 1 + 2 + 8 (tail); b: 1
    assert compute_stats(rows, now=NOW, tz=UTC)["today"]["practice_s"] == 12


def test_days_are_local_and_streak():
    tz = ZoneInfo("Europe/Kyiv")  # UTC+2 in November
    late = datetime(2026, 11, 17, 23, 0, tzinfo=UTC)  # already Nov 18 in Kyiv
    rows = [
        turn("a", "user", "x", datetime(2026, 11, 10, 9, tzinfo=UTC), audio_ms=1000),
        turn("b", "user", "x", datetime(2026, 11, 16, 9, tzinfo=UTC), audio_ms=1000),
        turn("c", "user", "x", late, audio_ms=1000),
    ]
    stats = compute_stats(rows, now=NOW, tz=tz, days=7)
    by_date = {d["date"]: d for d in stats["daily"]}
    assert len(stats["daily"]) == 7 and stats["daily"][-1]["date"] == "2026-11-19"
    assert by_date["2026-11-18"]["sessions"] == 1
    assert by_date["2026-11-17"]["sessions"] == 0
    # Nov 16 + Nov 18: not consecutive; today not practiced yet -> counts from yesterday.
    assert stats["streak"] == {"current_days": 1, "longest_days": 1, "practiced_today": False}
    assert stats["last_7_days"]["sessions"] == 2
    assert stats["totals"]["sessions"] == 3
    assert stats["first_day"] == "2026-11-10"


def test_streak_runs():
    rows = [turn(f"s{i}", "user", "x", NOW - timedelta(days=i), audio_ms=1000) for i in range(3)]
    assert compute_stats(rows, now=NOW, tz=UTC)["streak"] == {
        "current_days": 3, "longest_days": 3, "practiced_today": True}


def test_by_character_and_kind_and_wpm():
    rows = [
        turn("a", "user", " ".join(["w"] * 120), at(0), audio_ms=60_000),
        turn("b", "user", "x", at(10), audio_ms=1000, character="daniel"),
        turn("c", "user", "x y", at(20), audio_ms=1000, scenario="cafe"),
    ]
    stats = compute_stats(rows, now=NOW, tz=UTC, character_name=str.upper,
                          is_interview=lambda cid: cid == "daniel")
    assert stats["totals"]["words_per_minute"] == 119.0  # 123 words / 62s
    assert stats["by_kind"]["free"]["words_per_minute"] == 120.0
    assert stats["by_kind"]["interview"]["sessions"] == 1
    assert stats["by_kind"]["scenario"]["user_words"] == 2
    assert stats["by_kind"]["free"]["user_words"] == 120
    first = stats["by_character"][0]
    assert first["character_id"] == "emma" and first["name"] == "EMMA" and first["sessions"] == 2


def test_empty():
    stats = compute_stats([], now=NOW, tz=UTC, days=3)
    assert stats["totals"]["practice_s"] == 0 and stats["first_day"] is None
    assert [d["practice_s"] for d in stats["daily"]] == [0, 0, 0]


def test_db_stores_audio_ms_and_skips_sessions_without_user_turns(tmp_path):
    async def run():
        db = Database({"persistence": {"db_path": str(tmp_path / "t.db")}})
        await db.start()
        await db.create_session("a", character_id="emma")
        await db.add_turn("a", "assistant", "Hi!", audio_ms=1500)
        await db.add_turn("a", "user", "hello", audio_ms=900)
        await db.create_session("empty", character_id="emma")
        await db.add_turn("empty", "assistant", "Anyone?")
        rows = await db.stats_turns()
        await db.stop()
        return rows

    rows = asyncio.run(run())
    assert [(r["session_id"], r["role"], r["audio_ms"]) for r in rows] == [
        ("a", "assistant", 1500), ("a", "user", 900)]
    assert rows[0]["character_id"] == "emma"


class FakeStatsDb:
    def __init__(self, rows):
        self.rows = rows

    async def stats_turns(self):
        return self.rows


def test_stats_route_names_characters_and_rejects_bad_timezone(monkeypatch):
    from fastapi.testclient import TestClient

    from app.config import get_config
    from app.main import create_app

    monkeypatch.setenv("AI_ENGLISH__SECURITY__AUTH_REQUIRED", "false")
    get_config.cache_clear()
    try:
        app = create_app()
    finally:
        get_config.cache_clear()  # later tests get the real (auth on) config
    character = next(iter(app.state.preset_store.list()), None)
    cid = character.id if character else "ghost"
    app.state.db = FakeStatsDb([turn("s", "user", "hello there", datetime.now(UTC), audio_ms=2000, character=cid)])
    client = TestClient(app)  # no `with`: startup (models) doesn't run

    body = client.get("/stats", params={"days": 3, "tz": "Europe/Kyiv"}).json()
    assert body["today"]["speaking_s"] == 2 and len(body["daily"]) == 3
    assert body["by_character"][0]["name"] == (character.name if character else None)
    assert client.get("/stats", params={"tz": "Mars/Base"}).status_code == 400
    assert client.get("/stats", params={"days": 0}).status_code == 422
