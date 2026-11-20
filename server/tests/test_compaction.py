import asyncio

from app.conversation_engine import _SUMMARY_HEADER, ConversationEngine


class FakeOllama:
    """Stands in for `ollama.AsyncClient`. Non-streaming calls are either
    the compaction summary (last message is the app note) or the prewarm
    (`num_predict: 1`); `block` makes the named kind hang until cancelled."""

    def __init__(self, block: str | None = None):
        self.block = block
        self.calls: list[str] = []

    async def chat(self, model, messages, stream=False, think=None, options=None, keep_alive=None):
        if stream:
            return self._stream("Sure thing. ")
        kind = "prewarm" if (options or {}).get("num_predict") == 1 else "summary"
        self.calls.append(kind)
        if self.block == kind:
            await asyncio.Event().wait()
        return {"message": {"content": "" if kind == "prewarm" else "User has a beagle named Biscuit."}}

    async def _stream(self, text):
        yield {"message": {"content": text}}


def make_engine(fake: FakeOllama, keep: int = 4) -> ConversationEngine:
    engine = ConversationEngine(
        {"llm": {"model": "m", "compaction": {"trigger_tokens": 50, "keep_recent_messages": keep}}}
    )
    engine._client = fake
    return engine


def seed(engine: ConversationEngine, sid: str, exchanges: int) -> None:
    engine.start_session(sid, system_prompt="PERSONA")
    for i in range(exchanges):
        engine._histories[sid] += [
            {"role": "user", "content": f"user line {i} " * 5},
            {"role": "assistant", "content": f"bot line {i} " * 5},
        ]


async def reply(engine: ConversationEngine, sid: str, text: str) -> None:
    async for _ in engine.generate_reply(sid, text):
        pass


def test_cut_keeps_recent_messages_starting_on_a_user_turn():
    engine = make_engine(FakeOllama(), keep=5)
    history = [{"role": "system", "content": "s"}] + [
        {"role": r, "content": "x"} for _ in range(5) for r in ("user", "assistant")
    ]
    cut = engine._compaction_cut(history)
    assert history[cut]["role"] == "user"
    assert len(history) - cut == 6  # 5 rounded back to a whole exchange


def test_cut_needs_something_older_to_summarize():
    engine = make_engine(FakeOllama(), keep=6)
    short = [{"role": "system", "content": "s"}, {"role": "user", "content": "x"}]
    assert engine._compaction_cut(short) is None


def test_compaction_swaps_in_summary_after_prewarm():
    async def run():
        fake = FakeOllama()
        engine = make_engine(fake)
        seed(engine, "s", 10)
        await reply(engine, "s", "last question")
        await engine._compaction_tasks["s"]
        return fake, engine._histories["s"]

    fake, history = asyncio.run(run())
    assert fake.calls == ["summary", "prewarm"]
    assert history[0]["role"] == "system"
    assert history[0]["content"].startswith("PERSONA\n\n" + _SUMMARY_HEADER)
    assert "Biscuit" in history[0]["content"]
    assert [m["role"] for m in history[1:]] == ["user", "assistant"] * 2
    assert history[-2]["content"] == "last question"


def test_user_turn_cancels_summary_and_history_stays_intact():
    async def run():
        fake = FakeOllama(block="summary")
        engine = make_engine(fake)
        seed(engine, "s", 10)
        await reply(engine, "s", "first")
        task = engine._compaction_tasks["s"]
        await asyncio.sleep(0)
        await reply(engine, "s", "second")  # must not wait on the blocked summary
        return engine, task

    engine, task = asyncio.run(run())
    assert task.cancelled()
    assert "s" not in engine._pending_summaries
    history = engine._histories["s"]
    assert history[0]["content"] == "PERSONA"
    assert history[-2]["content"] == "second"


def test_cancel_during_prewarm_keeps_summary_for_next_attempt():
    async def run():
        fake = FakeOllama(block="prewarm")
        engine = make_engine(fake)
        seed(engine, "s", 10)
        await reply(engine, "s", "first")
        while fake.calls != ["summary", "prewarm"]:
            await asyncio.sleep(0)
        await reply(engine, "s", "second")
        assert "s" in engine._pending_summaries

        fake.block = None
        await engine._compaction_tasks["s"]  # restarted after "second"
        return fake, engine

    fake, engine = asyncio.run(run())
    assert fake.calls == ["summary", "prewarm", "prewarm"]  # summary not redone
    assert "Biscuit" in engine._histories["s"][0]["content"]
    assert engine._histories["s"][-2]["content"] == "second"


def test_end_session_cancels_compaction():
    async def run():
        engine = make_engine(FakeOllama(block="summary"))
        seed(engine, "s", 10)
        await reply(engine, "s", "first")
        task = engine._compaction_tasks["s"]
        engine.end_session("s")
        await asyncio.wait({task})
        return task, engine

    task, engine = asyncio.run(run())
    assert task.cancelled()
    assert "s" not in engine._histories
