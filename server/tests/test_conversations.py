import asyncio

from app.conversation_engine import _SUMMARY_HEADER, ConversationEngine, parse_wrap_up
from app.db import Database
from app.main import conversation_summary


class FakeOllama:
    """Records non-streaming calls; `block` makes them hang until released."""

    def __init__(self, reply: str = "", block: bool = False):
        self.reply = reply
        self.calls: list[list[dict]] = []
        self.release = asyncio.Event()
        if not block:
            self.release.set()

    async def chat(self, model, messages, stream=False, think=None, options=None, keep_alive=None):
        if stream:
            return self._stream("Sure thing. ")
        self.calls.append([dict(m) for m in messages])
        await self.release.wait()
        return {"message": {"content": self.reply}}

    async def _stream(self, text):
        yield {"message": {"content": text}}


def make_engine(fake=None, trigger: int = 0, keep: int = 4) -> ConversationEngine:
    engine = ConversationEngine(
        {"llm": {"model": "m", "compaction": {"trigger_tokens": trigger * 4, "resume_tokens": trigger,
                                              "keep_recent_messages": keep}}}
    )
    engine._client = fake or FakeOllama()
    return engine


def turns(*pairs):
    return [{"role": role, "text": text} for role, text in pairs]


def test_restore_full_history_merges_same_role_and_drops_unanswered_tail():
    engine = make_engine()
    history, mode = engine.restore_history("PERSONA", turns(
        ("assistant", "Welcome!"), ("user", "hi"), ("user", "are you there"),
        ("assistant", "Yes."), ("user", "lost reply"),
    ))
    assert mode == "full"
    assert history == [
        {"role": "system", "content": "PERSONA"},
        {"role": "assistant", "content": "Welcome!"},
        {"role": "user", "content": "hi\nare you there"},
        {"role": "assistant", "content": "Yes."},
    ]


def long_conversation(n: int = 10):
    return turns(*[(r, f"{r} line {i} " * 5) for i in range(n) for r in ("user", "assistant")])


def test_restore_long_history_uses_saved_notes_plus_recent_turns():
    engine = make_engine(trigger=50, keep=4)
    history, mode = engine.restore_history("PERSONA", long_conversation(), summary="Has a beagle.")
    assert mode == "summary"
    assert history[0]["content"] == f"PERSONA\n\n{_SUMMARY_HEADER}\nHas a beagle."
    assert [m["role"] for m in history[1:]] == ["user", "assistant"] * 2
    assert history[-1]["content"].startswith("assistant line 9")


def test_restore_long_history_without_notes_keeps_what_fits():
    engine = make_engine(trigger=50)
    history, mode = engine.restore_history("PERSONA", long_conversation())
    assert mode == "truncated"
    assert history[0] == {"role": "system", "content": "PERSONA"}
    assert history[1]["role"] == "user"
    assert history[-1]["content"].startswith("assistant line 9")
    assert len(history) < 21


def test_resumed_session_prewarms_whole_history_and_first_turn_waits_for_it():
    async def run():
        fake = FakeOllama(block=True)
        engine = make_engine(fake)
        restored, _ = engine.restore_history("PERSONA", turns(("user", "hi"), ("assistant", "Hello!")))
        engine.start_session("s", system_prompt="PERSONA", restored=restored)
        await asyncio.sleep(0)
        turn = asyncio.create_task(_reply(engine, "s", "next"))
        await asyncio.sleep(0.01)
        prewarm_alive = any(not t.done() for t in engine._prewarm_tasks.values())
        fake.release.set()
        await turn
        return fake, prewarm_alive, engine

    fake, prewarm_alive, engine = asyncio.run(run())
    assert prewarm_alive  # the user turn didn't cancel it
    assert [m["role"] for m in fake.calls[0]] == ["system", "user", "assistant"]
    assert engine._base_prompts["s"] == "PERSONA"


async def _reply(engine, sid, text):
    async for _ in engine.generate_reply(sid, text):
        pass


def test_wrap_up_asks_for_notes_only_when_requested():
    async def run(with_notes):
        fake = FakeOllama(reply="**Title: Weekend Hiking Plans**\n\nNotes: User likes hiking.")
        engine = make_engine(fake)
        result = await engine.wrap_up("s", [{"role": "system", "content": "P"}], with_notes)
        return result, fake.calls[0][-1]["content"]

    (title, notes), note = asyncio.run(run(False))
    assert (title, notes) == ("Weekend Hiking Plans", None)
    assert "notes" not in note.lower()
    (title, notes), note = asyncio.run(run(True))
    assert (title, notes) == ("Weekend Hiking Plans", "User likes hiking.")


def test_parse_wrap_up_strips_quotes_and_handles_empty():
    assert parse_wrap_up('"Coffee Shop Order"', False) == ("Coffee Shop Order", None)
    assert parse_wrap_up("  ", True) == (None, None)


def test_db_lists_resumable_conversations_and_deletes(tmp_path):
    async def run():
        db = Database({"persistence": {"db_path": str(tmp_path / "t.db")}})
        await db.start()
        await db.create_session("empty", character_id="emma")
        await db.create_session("a", character_id="emma", english_level="B2", use_memory=False)
        await db.add_turn("a", "assistant", "Hi!")
        await db.add_turn("a", "user", "I like snow")
        await db.save_wrap_up("a", "Snow Talk", None, 2)
        before = (await db.get_transcript("a"))[-1]["ts"]
        await db.add_turn("a", "user", "later line")
        listed = await db.list_conversations()
        renamed = await db.rename_session("a", "My Title")
        await db.save_wrap_up("a", "Model Title", None, 3)
        kept = (await db.get_session("a"))["title"]
        since = await db.get_transcript("a", since=before)
        row = await db.get_session("a")
        deleted = await db.delete_session("a")
        after = await db.list_conversations()
        await db.stop()
        return listed, since, row, deleted, after, renamed, kept

    listed, since, row, deleted, after, renamed, kept = asyncio.run(run())
    assert renamed and kept == "My Title"  # the wrap-up doesn't overwrite a hand-set title
    assert [c["id"] for c in listed] == ["a"]  # no user turns: hidden
    assert listed[0]["title"] == "Snow Talk" and listed[0]["topic"] == "I like snow"
    assert listed[0]["user_turns"] == 2 and listed[0]["turns"] == 3
    assert [t["text"] for t in since] == ["later line"]
    assert row["english_level"] == "B2" and row["use_memory"] == 0
    assert deleted and after == []


class Presets:
    def get(self, cid):
        return type("P", (), {"name": "Emma"})() if cid == "emma" else None


def test_conversation_summary_marks_deleted_character_and_active():
    base = {"id": "a", "started_at": "t", "topic": "word " * 40}
    item = conversation_summary({**base, "character_id": "emma"}, Presets(), "a")
    assert item["character_name"] == "Emma" and item["can_resume"] and item["active"]
    assert len(item["topic"]) <= 81 and item["topic"].endswith("…")
    gone = conversation_summary({**base, "character_id": "jamie_test"}, Presets(), None)
    assert gone["character_name"] is None and not gone["can_resume"] and not gone["active"]
