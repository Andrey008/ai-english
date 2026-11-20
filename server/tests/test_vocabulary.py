import asyncio
import json

from app.db import Database
from app.vocabulary import (
    VocabularyService,
    anchor_bookmarks,
    find_context,
    focus,
    is_ask,
    merge,
    parse_asked,
    parse_bookmarked,
    render_transcript,
)


def line(role, text, ts):
    return {"role": role, "text": text, "ts": ts}


LINES = [
    line("assistant", "Hi! How was your weekend?", "t01"),
    line("user", "good I went hiking", "t02"),
    line("assistant", "Nice! Were you reluctant to get up early? It sounds like a piece of cake for you.", "t03"),
    line("user", "what does reluctant mean", "t04"),
    line("assistant", "Reluctant means you don't really want to do something.", "t05"),
]


class FakeOllama:
    """`reply` answers the ask prompt, `bookmark_reply` the bookmark one."""

    def __init__(self, reply=None, fail=False, bookmark_reply=None):
        self.reply = reply if reply is not None else {"words": []}
        self.bookmark_reply = bookmark_reply if bookmark_reply is not None else {"words": []}
        self.fail = fail
        self.prompts: list[str] = []

    async def chat(self, model, messages, stream=False, think=None, format=None, options=None, keep_alive=None):
        prompt = messages[-1]["content"]
        self.prompts.append(prompt)
        if self.fail:
            raise ConnectionError("down")
        reply = self.bookmark_reply if "pressed a button" in prompt else self.reply
        return {"message": {"content": json.dumps(reply)}}


def service(db, fake):
    svc = VocabularyService({"llm": {"model": "m"}}, db)
    svc._client = fake
    return svc


def test_re_ask_detection():
    assert is_ask(LINES[3])
    assert not is_ask(LINES[2])  # character lines never count
    for plain in ("I like hiking in the mountains", "what is your favorite food"):
        assert not is_ask(line("user", plain, "t1")), plain
    for asked in ("what is a sheepdog?", "sorry, what's a hike?", "I don't understand", "I never heard this word",
                  "Pardon, meaning?", "Sorry, crisp?", "Actually, I didn't get what you mean with this word robust"):
        assert is_ask(line("user", asked, "t1")), asked


def test_bookmark_anchors_to_the_line_playing_or_just_played():
    # pressed after t03 was spoken (listening) → t03
    assert anchor_bookmarks(LINES, ["t035"]) == {2}
    # pressed while the reply to t04 was being spoken (saved at t05) → t05
    assert anchor_bookmarks(LINES, ["t045"]) == {4}
    # after everything → the last line
    assert anchor_bookmarks(LINES, ["t09"]) == {4}
    # before any character line → nothing
    assert anchor_bookmarks([line("user", "hi", "t1"), line("assistant", "Hello.", "t3")], ["t0"]) == set()


def test_render_numbers_lines_and_marks_gaps():
    text = render_transcript(LINES[:3], {0})
    assert text.splitlines() == ["1. CHARACTER: Hi! How was your weekend?", "...", "2. USER: good I went hiking",
                                 "3. CHARACTER: Nice! Were you reluctant to get up early? It sounds like a piece of cake for you."]


def test_context_is_the_sentence_with_the_word():
    text = LINES[2]["text"]
    assert find_context("reluctant", text) == "Were you reluctant to get up early?"
    assert find_context("a piece of cake", text).startswith("It sounds like")
    assert find_context("serendipity", text) is None


def test_parse_asked_keeps_words_tied_to_a_real_question():
    raw = json.dumps({"words": [
        {"word": "Reluctant", "line": 4, "asked_in": 4, "explanation": "not wanting to do something",
         "translation_ru": "неохотный"},  # points at the user's line; found in line 3
        {"word": "early", "line": 3, "asked_in": 2},  # line 2 asks nothing
        {"word": "nice", "line": 3},  # no asked_in
        {"word": "flabbergasted", "line": 3, "asked_in": 4},  # invented
        {"word": "something", "line": 5, "asked_in": 4},  # only said after the question
        {"word": "", "line": 3, "asked_in": 4},
        "junk",
    ]})
    [row] = parse_asked(raw, LINES)
    assert row == {"word": "Reluctant", "word_key": "reluctant", "context": "Were you reluctant to get up early?",
                   "explanation": "not wanting to do something", "translation_ru": "неохотный", "source": "asked"}
    assert parse_asked("not json", LINES) == []
    assert parse_asked('{"words": "x"}', LINES) == []


def test_parse_bookmarked_needs_the_word_in_a_marked_line():
    marked = [LINES[2]]
    raw = json.dumps({"words": [{"word": "a piece of cake", "line": 1, "translation_ru": "проще простого"},
                                {"word": "bookmark", "line": 1}, {"word": "a", "line": 1}]})
    [row] = parse_bookmarked(raw, marked)
    assert row["source"] == "bookmark" and row["context"] == "It sounds like a piece of cake for you."


def test_merge_prefers_the_asked_row():
    asked = [{"word_key": "x", "source": "asked"}]
    assert merge(asked, [{"word_key": "x", "source": "bookmark"}, {"word_key": "y", "source": "bookmark"}]) == [
        {"word_key": "x", "source": "asked"}, {"word_key": "y", "source": "bookmark"}]


def make_db(tmp_path):
    return Database({"persistence": {"db_path": str(tmp_path / "t.db")}})


async def talk(db, sid, *lines):
    for role, text in lines:
        await db.add_turn(sid, role, text)


def test_scan_reads_only_the_new_visit_and_counts_repeats(tmp_path):
    async def run():
        db = make_db(tmp_path)
        await db.start()
        await db.create_session("s", character_id="emma")
        await talk(db, "s", ("assistant", "Were you reluctant to go?"), ("user", "what does reluctant mean"))
        fake = FakeOllama({"words": [{"word": "reluctant", "line": 1, "asked_in": 2, "translation_ru": "неохотный"}]})
        svc = service(db, fake)
        assert [w["word"] for w in await svc.scan_session("s")] == ["reluctant"]

        # nothing new → no LLM call
        assert await svc.scan_session("s") == []
        assert len(fake.prompts) == 1

        # next visit: no question → watermark moves, no call
        await talk(db, "s", ("assistant", "Tell me more, my reluctant hiker."), ("user", "I went to the lake"))
        assert await svc.scan_session("s") == []
        assert len(fake.prompts) == 1

        # next visit asks about the last line of the previous one
        await talk(db, "s", ("user", "sorry, what does reluctant mean"))
        fake.reply = {"words": [{"word": "reluctant", "line": 1, "asked_in": 2}]}
        await svc.scan_session("s")
        prompt = fake.prompts[-1]
        assert "1. CHARACTER: Tell me more, my reluctant hiker." in prompt  # the line before the visit
        assert "Were you reluctant to go" not in prompt  # older history is not re-read
        [row] = await db.list_vocabulary()
        assert row["times_seen"] == 2 and row["translation_ru"] == "неохотный"
        await db.stop()

    asyncio.run(run())


def test_scan_failure_keeps_the_watermark_for_a_retry(tmp_path):
    async def run():
        db = make_db(tmp_path)
        await db.start()
        await db.create_session("s")
        await talk(db, "s", ("assistant", "That's ubiquitous."), ("user", "what does ubiquitous mean"))
        fake = FakeOllama({"words": [{"word": "ubiquitous", "line": 1, "asked_in": 2}]}, fail=True)
        svc = service(db, fake)
        assert await svc.scan_session("s") is None
        fake.fail = False
        assert [w["word"] for w in await svc.scan_session("s")] == ["ubiquitous"]
        await db.stop()

    asyncio.run(run())


def test_bookmark_triggers_and_marks_the_line(tmp_path):
    async def run():
        db = make_db(tmp_path)
        await db.start()
        await db.create_session("s")
        await talk(db, "s", ("assistant", "It was a serendipitous encounter."))
        await db.add_bookmark("s")
        await talk(db, "s", ("user", "yes it was"))
        fake = FakeOllama(bookmark_reply={"words": [{"word": "serendipitous", "line": 1}]})
        words = await service(db, fake).scan_session("s")
        assert len(fake.prompts) == 1  # no re-ask → no ask prompt
        assert "1. It was a serendipitous encounter." in fake.prompts[0]
        assert words[0]["source"] == "bookmark"
        await db.stop()

    asyncio.run(run())


def test_status_changes_and_survive_conversation_delete(tmp_path):
    async def run():
        db = make_db(tmp_path)
        await db.start()
        await db.create_session("s")
        await db.upsert_vocabulary("s", [
            {"word": "a", "word_key": "a", "source": "asked"},
            {"word": "b", "word_key": "b", "source": "asked"},
        ])
        rows = await db.list_vocabulary()
        await db.set_vocabulary_status([r["id"] for r in rows], "added")
        assert len(await db.list_vocabulary("added")) == 2
        await db.upsert_vocabulary("s", [{"word": "a", "word_key": "a", "source": "asked"}])
        assert len(await db.list_vocabulary("added")) == 2  # status kept on a repeat
        await db.add_bookmark("s")
        await db.delete_session("s")
        assert len(await db.list_vocabulary()) == 2
        assert await db.delete_vocabulary(rows[0]["id"])
        assert len(await db.list_vocabulary()) == 1
        await db.stop()

    asyncio.run(run())


def test_migration_starts_existing_conversations_fully_scanned(tmp_path):
    async def run():
        db = make_db(tmp_path)
        await db.start()
        await db.create_session("old")
        await talk(db, "old", ("assistant", "Ubiquitous!"), ("user", "what does ubiquitous mean"))
        # simulate the row as it was before 0009: re-run its UPDATE
        await db._conn.execute(
            "UPDATE sessions SET vocab_scanned_until = (SELECT MAX(ts) FROM turns WHERE turns.session_id = sessions.id)"
        )
        fake = FakeOllama()
        assert await service(db, fake).scan_session("old") == []
        assert fake.prompts == []
        await db.stop()

    asyncio.run(run())


def test_focus_keeps_only_the_lines_around_re_asks():
    lines = [line("assistant", f"Line {i}.", f"t{i:02}") if i % 2 == 0 else line("user", "fine", f"t{i:02}")
             for i in range(12)]
    lines[7] = line("user", "sorry, crisp?", "t07")
    excerpt, gaps = focus(lines)
    assert [l["ts"] for l in excerpt] == ["t04", "t05", "t06", "t07", "t08"]
    assert gaps == set()
    lines[1] = line("user", "what does it mean", "t01")
    excerpt, gaps = focus(lines)
    assert [l["ts"] for l in excerpt] == ["t00", "t01", "t02", "t04", "t05", "t06", "t07", "t08"]
    assert gaps == {2}
    assert focus(lines[2:4]) == ([], set())


def test_question_must_name_the_word_or_none():
    from app.vocabulary import asks_about

    assert asks_about("What do you mean crisp?", "crisp")
    assert asks_about("Actually, I didn't get what you mean with this word robust.", "robust")
    assert asks_about("sorry what does robast mean", "robust")  # STT misspelling
    assert asks_about("Sorry, what does that mean?", "lucrative")  # names no word
    assert not asks_about("Before I try, can you explain what the mind needs?", "determined")
    assert not asks_about("Can you rephrase it because I didn't get your question?", "remote work")
    long = " ".join(["word"] * 30) + " they don't understand"
    assert not is_ask(line("user", long, "t1"))


def test_bookmark_words_are_capped_per_line_and_context_is_clean():
    marked = [line("assistant", "It's *lucrative*, robust and ubiquitous.", "t1")]
    raw = json.dumps({"words": [{"word": w, "line": 1} for w in ("lucrative", "robust", "ubiquitous")]})
    rows = parse_bookmarked(raw, marked, per_line=2)
    assert [r["word"] for r in rows] == ["lucrative", "robust"]
    assert rows[0]["context"] == "It's lucrative, robust and ubiquitous."


def test_after_session_runs_the_pass_even_if_the_wrap_up_fails():
    from types import SimpleNamespace

    from app.ws_session import _after_session

    calls = []

    class BrokenDb:
        async def get_transcript(self, session_id):
            raise RuntimeError("boom")

    class Vocab:
        enabled = True

        async def scan_session(self, session_id, level):
            calls.append((session_id, level))

    app = SimpleNamespace(state=SimpleNamespace(
        db=BrokenDb(), conversation_engine=None, vocabulary_service=Vocab(), character_memory_service=None,
    ))
    asyncio.run(_after_session(app, "s", [], None, None, "B2"))
    assert calls == [("s", "B2")]
    Vocab.enabled = False
    asyncio.run(_after_session(app, "s", [], None, None, "B2"))
    assert len(calls) == 1
