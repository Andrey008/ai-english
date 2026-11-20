import asyncio

from app.conversation_engine import ConversationEngine


class FakeOllama:
    """Streams a fixed reply; non-streaming calls are the reply prewarm.
    `block` makes the prewarm hang until cancelled."""

    def __init__(self, block: bool = False):
        self.block = block
        self.prewarms: list[list[dict]] = []
        self.cancelled = 0

    async def chat(self, model, messages, stream=False, think=None, options=None, keep_alive=None):
        if stream:
            return self._stream("Sure thing. ")
        assert options == {"num_predict": 1}  # never a different num_ctx: that would reload the model
        self.prewarms.append([dict(m) for m in messages])
        if self.block:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled += 1
                raise
        return {"message": {"content": ""}}

    async def _stream(self, text):
        yield {"message": {"content": text}}


def make_engine(fake: FakeOllama, **llm) -> ConversationEngine:
    engine = ConversationEngine({"llm": {"model": "m", **llm}})
    engine._client = fake
    return engine


async def reply(engine: ConversationEngine, sid: str, text: str) -> None:
    async for _ in engine.generate_reply(sid, text):
        pass


def test_reply_is_prewarmed_with_history_plus_own_reply():
    async def run():
        fake = FakeOllama()
        engine = make_engine(fake)
        engine.start_session("s", system_prompt="PERSONA")
        await reply(engine, "s", "hi")
        await engine._reply_prewarm_tasks["s"]
        await reply(engine, "s", "next")
        return fake, engine._histories["s"]

    fake, history = asyncio.run(run())
    first = fake.prewarms[0]
    assert [m["role"] for m in first] == ["system", "user", "assistant"]
    assert first[-1]["content"] == "Sure thing. "
    assert history[: len(first)] == first  # the next request extends exactly what was cached


def test_next_user_turn_cancels_a_prewarm_still_in_flight():
    async def run():
        fake = FakeOllama(block=True)
        engine = make_engine(fake)
        engine.start_session("s", system_prompt="PERSONA")
        await reply(engine, "s", "hi")
        await asyncio.sleep(0)  # let the prewarm start
        await reply(engine, "s", "cut in")
        return fake.cancelled, engine

    cancelled, engine = asyncio.run(run())
    assert cancelled == 1  # counted before shutdown cancels the second reply's own prewarm
    assert [m["content"] for m in engine._histories["s"] if m["role"] == "user"] == ["hi", "cut in"]


def test_reply_prewarm_can_be_disabled():
    async def run():
        fake = FakeOllama()
        engine = make_engine(fake, reply_prewarm=False)
        engine.start_session("s", system_prompt="PERSONA")
        await reply(engine, "s", "hi")
        return fake, engine

    fake, engine = asyncio.run(run())
    assert fake.prewarms == [] and "s" not in engine._reply_prewarm_tasks


def test_end_session_cancels_reply_prewarm():
    async def run():
        fake = FakeOllama(block=True)
        engine = make_engine(fake)
        engine.start_session("s", system_prompt="PERSONA")
        await reply(engine, "s", "hi")
        await asyncio.sleep(0)
        task = engine._reply_prewarm_tasks["s"]
        engine.end_session("s")
        await asyncio.wait({task})
        return fake

    assert asyncio.run(run()).cancelled == 1


def test_last_reply_is_the_characters_latest_line():
    engine = make_engine(FakeOllama(), reply_prewarm=False)

    async def run():
        engine.start_session("s", system_prompt="PERSONA", opening_message="Hi, I'm Emma!")
        first = engine.last_reply("s")
        await reply(engine, "s", "hi")
        return first, engine.last_reply("s")

    assert asyncio.run(run()) == ("Hi, I'm Emma!", "Sure thing. ")
    assert engine.last_reply("unknown") is None
