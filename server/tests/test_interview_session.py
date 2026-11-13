import asyncio
import json
from pathlib import Path

import pytest

from app.db import Database
from app.interview import prompts
from app.interview.builder import interview_options, state_from_rows
from app.interview.session import InterviewItem, InterviewState, detect_command, is_followup
from app.persona import render_level_addendum, render_system_prompt
from app.presets import CharacterPreset
from app.ws_session import compose_system_prompt

from tests.test_conversations import FakeOllama, make_engine


def state(n=3, followups=1):
    items = [InterviewItem(idx=i, question_id=f"q{i}", category="c", question_ru=f"вопрос {i}",
                           question_en=f"Question {i}?") for i in range(n)]
    return InterviewState(name="Daniel", items=items, max_followups=followups)


@pytest.mark.parametrize("text, command", [
    ("Can you repeat the question?", "repeat"),
    ("Sorry, say that again please.", "repeat"),
    ("What do you mean?", "rephrase"),
    ("I don't understand the question.", "rephrase"),
    ("Let's skip this one.", "skip"),
    ("Next question, please.", "skip"),
    ("I'll pass.", "skip"),
    ("Kip this one.", "skip"),
    ("I don't know, maybe a cache?", None),          # a real (short) answer, not a skip
    ("We used a queue so we could move on quickly when one store failed and the others kept going.", None),
    ("", None),
])
def test_detect_command(text, command):
    assert detect_command(text) == command


def test_opening_followup_then_advance():
    s = state()
    assert s.opening().endswith("Question 0?") and "three questions" in s.opening()
    plan = s.plan_turn("We used Magento plugins.")
    assert plan.followup_allowed and prompts.FOLLOWUP_NOTE in plan.llm_text
    assert plan.llm_text.startswith("We used Magento plugins.")
    assert s.finish_reply(plan, "Why plugins and not observers?") is None      # follow-up asked
    assert s.followups_used == 1 and s.index == 0
    plan = s.plan_turn("Because they wrap the method.")
    assert plan.kind == "scripted" and plan.scripted_text == f"{prompts.ACKS[0]} Question 1?"
    assert (s.index, s.followups_used) == (1, 0)
    assert [i.status for i in s.items] == ["answered", "asked", "pending"]


def test_complete_answer_advances_without_followup():
    s = state()
    s.opening()
    plan = s.plan_turn("A full answer.")
    assert s.finish_reply(plan, "Okay, thank you.") == "Question 1?"


def test_last_question_closes():
    s = state(n=2, followups=0)
    s.opening()
    plan = s.plan_turn("answer one")
    assert plan.scripted_text == f"{prompts.ACKS[0]} And the last question. Question 1?"
    plan = s.plan_turn("answer two")
    assert plan.scripted_text == f"{prompts.ACKS[1]} {prompts.CLOSING_LINE}"
    assert s.finished and [i.status for i in s.items] == ["answered", "answered"]


def test_commands_skip_repeat_rephrase():
    s = state()
    s.opening()
    plan = s.plan_turn("Repeat the question, please.")
    assert plan.kind == "scripted" and plan.scripted_text == "Question 0?" and s.index == 0
    plan = s.plan_turn("What do you mean?")
    assert plan.kind == "llm" and prompts.REPHRASE_NOTE in plan.llm_text
    assert s.finish_reply(plan, "How do you extend Magento?") is None and s.followups_used == 0
    plan = s.plan_turn("Skip this one.")
    assert plan.kind == "scripted" and plan.scripted_text == f"{prompts.SKIP_LINE} Question 1?"
    assert plan.question_idx == 0 and s.index == 1
    assert [i.status for i in s.items] == ["skipped", "asked", "pending"]


def test_take_changes_and_resume():
    s = state()
    s.opening()
    s.take_changes()
    s.finish_reply(s.plan_turn("x"), "Okay.")
    assert [(i.idx, i.status) for i in s.take_changes()] == [(0, "answered"), (1, "asked")]
    assert s.take_changes() == []

    rows = [dict(i.as_row()) for i in s.items]
    resumed = state_from_rows("Daniel", rows, 1)
    assert resumed.index == 1 and resumed.resume_line().endswith("question two. Question 1?")
    done = state_from_rows("Daniel", [dict(r, status="answered") for r in rows], 1)
    assert done.finished and done.resume_line() == prompts.ALREADY_DONE_LINE


def test_interview_options_clamp():
    cfg = {"interview": {"question_count": 10, "max_followups": 1}}
    assert interview_options(cfg, None) == {"count": 10, "max_followups": 1, "categories": None}
    assert interview_options(cfg, {"count": 99, "max_followups": "x", "categories": ["api"]}) == {
        "count": 30, "max_followups": 1, "categories": ["api"]}


# ---- prompts: other characters unchanged --------------------------------

CHARACTERS = Path(__file__).resolve().parent.parent / "data" / "characters"


def load(name):
    return CharacterPreset.model_validate_json((CHARACTERS / f"{name}.json").read_text())


@pytest.mark.parametrize("name", ["alex_default", "emma_teacher", "oliver_uk_friend", "sarah_interview_coach"])
def test_conversation_characters_prompt_unchanged(name):
    preset = load(name)
    assert preset.session_mode == "conversation"
    expected = (preset.system_prompt_override or render_system_prompt(
        preset.name, preset.role_description, preset.correction_style)) + "\n\n" + render_level_addendum("B1")
    assert compose_system_prompt(preset, None, "B1", None) == expected


def test_interviewer_prompt():
    preset = load("daniel_interviewer")
    assert preset.session_mode == "interview" and not preset.memory_enabled
    prompt = compose_system_prompt(preset, object(), "B2", "memory that must not appear")
    assert prompt.startswith("You are Daniel.") and "PROACTIVE" not in prompt
    assert "Interviewer note" in prompt and "memory that must not appear" not in prompt
    assert prompt.endswith(render_level_addendum("B2"))


# ---- engine ------------------------------------------------------------

def collect(engine, sid, text, suffix=None):
    async def go():
        return [e async for e in engine.generate_reply(sid, text, reply_suffix=suffix)]
    return asyncio.run(go())


def test_reply_suffix_is_spoken_and_stored():
    engine = make_engine(FakeOllama())
    engine._reply_prewarm = False
    engine.start_session("s", system_prompt="sys")
    seen = []
    events = collect(engine, "s", "answer\n\n[note]", lambda reply: seen.append(reply) or "Next one. Question 2?")
    sentences = [e["text"] for e in events if e["type"] == "sentence"]
    assert seen == ["Sure thing. "] and sentences == ["Sure thing.", "Next one.", "Question 2?"]
    assert events[-1]["full_text"] == "Sure thing. Next one. Question 2?"
    assert engine.history("s")[-1] == {"role": "assistant", "content": "Sure thing. Next one. Question 2?"}
    assert engine.history("s")[-2]["content"] == "answer\n\n[note]"


def test_append_exchange():
    engine = make_engine(FakeOllama())
    engine._reply_prewarm = False
    fake = engine._client

    async def go():
        engine.start_session("s", system_prompt="sys", opening_message="Q1?")
        await asyncio.sleep(0)                                   # let the opening prewarm run
        await engine.append_exchange("s", "repeat please", "Q1?")
    asyncio.run(go())
    assert [m["role"] for m in fake.calls[0]] == ["system", "assistant"]   # opening cached
    assert [m["role"] for m in engine.history("s")] == ["system", "assistant", "user", "assistant"]


# ---- db ------------------------------------------------------------------

def test_db_interview_items(tmp_path):
    async def go():
        db = Database({"persistence": {"db_path": str(tmp_path / "t.db")}})
        await db.start()
        for sid in ("old", "new"):
            await db.create_session(sid, character_id="daniel_interviewer")
        s = state()
        await db.create_interview_items("old", [i.as_row() for i in s.items])
        await db.set_interview_item_status("old", 0, "answered")
        await db.create_interview_items("new", [dict(i.as_row(), question_id=f"n{i.idx}") for i in s.items])
        await db.set_interview_item_status("new", 1, "skipped")
        assert await db.recent_interview_question_ids(5) == {"q0", "n1"}     # pending ones don't count
        rows = await db.get_interview_items("old")
        assert [r["status"] for r in rows] == ["answered", "pending", "pending"]
        await db.add_turn("old", "user", "hi", question_idx=0)
        assert (await db.get_transcript("old"))[0]["question_idx"] == 0
        assert await db.delete_session("old")
        assert await db.get_interview_items("old") == []
        await db.stop()
    asyncio.run(go())


@pytest.mark.parametrize("reply, followup", [
    ("Okay, thank you.", False),
    ("Got it.", False),
    ("Okay, thanks for walking me through that in detail.", False),
    ("Why plugins and not observers?", True),
    ("Okay, thank you. Tell me more about your experience with Java microservices.", True),
    ("Describe the retry logic.", True),
    ("That's interesting, and I'd like to hear a little more about the queue part of it.", True),
])
def test_is_followup(reply, followup):
    assert is_followup(reply) is followup
