"""Session-start warmup: keep_alive, model loading, the `preparing` state."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.conversation_engine import ConversationEngine
from app.ws_session import _wait_until_prepared


class FakeOllama:
    def __init__(self, loaded: bool = False, prewarm_s: float = 0.0):
        self.loaded = loaded
        self.prewarm_s = prewarm_s
        self.calls: list[tuple[str, dict]] = []

    async def ps(self):
        models = [SimpleNamespace(model="m", name="m")] if self.loaded else []
        return SimpleNamespace(models=models)

    async def generate(self, **kwargs):
        self.calls.append(("generate", kwargs))
        if kwargs.get("prompt") == "":
            self.loaded = True
        return {}

    async def chat(self, **kwargs):
        self.calls.append(("chat", kwargs))
        await asyncio.sleep(self.prewarm_s)
        return {"message": {"content": ""}}


class FakeSocket:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)


def make_engine(fake: FakeOllama, **llm) -> ConversationEngine:
    engine = ConversationEngine({"llm": {"model": "m", **llm}})
    engine._client = fake
    return engine


def test_warm_model_loads_once_and_reports():
    async def run():
        fake = FakeOllama(loaded=False)
        engine = make_engine(fake, keep_alive="2h")
        first = await engine.warm_model()
        second = await engine.warm_model()
        return fake, first, second

    fake, first, second = asyncio.run(run())
    assert first["loaded"] is True and first["load_s"] >= 0
    assert second == {"loaded": True, "load_s": 0.0}
    loads = [kw for name, kw in fake.calls if name == "generate"]
    assert len(loads) == 1 and loads[0]["keep_alive"] == "2h"


def test_every_prewarm_call_carries_keep_alive():
    async def run():
        fake = FakeOllama(loaded=True)
        engine = make_engine(fake, keep_alive="1h")
        engine.start_session("s", system_prompt="You are Emma.", opening_message="Hi there!")
        await asyncio.sleep(0.01)
        return fake

    fake = asyncio.run(run())
    assert fake.calls and all(kw.get("keep_alive") == "1h" for _, kw in fake.calls)


def test_quick_prewarm_sends_no_preparing_state():
    async def run():
        engine = make_engine(FakeOllama(loaded=True, prewarm_s=0.05))
        engine.start_session("s", system_prompt="p", opening_message="Hello.")
        ws = FakeSocket()
        await _wait_until_prepared(ws, engine, "s")
        return ws

    assert asyncio.run(run()).sent == []


def test_slow_prewarm_announces_preparing_and_waits_for_it():
    async def run():
        fake = FakeOllama(loaded=False, prewarm_s=0.8)
        engine = make_engine(fake, model_load_s=5, prefill_tok_s=100)
        engine.start_session("s", system_prompt="p", opening_message="Hello.")
        ws = FakeSocket()
        await _wait_until_prepared(ws, engine, "s")
        return ws, engine

    ws, engine = asyncio.run(run())
    assert len(ws.sent) == 1
    msg = ws.sent[0]
    assert msg["type"] == "session_state" and msg["state"] == "preparing"
    assert msg["model_loading"] is True
    assert msg["expected_s"] >= 5  # load time guess + prompt prefill
    assert engine.prewarm_pending("s") is None  # it waited until the prewarm finished


def test_no_prewarm_no_wait():
    async def run():
        engine = make_engine(FakeOllama())
        ws = FakeSocket()
        await _wait_until_prepared(ws, engine, "unknown")
        return ws

    assert asyncio.run(run()).sent == []
