import asyncio
import json
import os

import httpx
import pytest

from app.claude_gateway import ClaudeGateway, GatewayError, GatewayResult
from app.config import load_dotenv
from app.db import Database
from app.interview.prep_client import PrepQuestion
from app.interview.translation import needs_translation, parse_reply, source_hash, translate_missing


def q(id_, ru):
    return PrepQuestion(id=id_, category="c", question_ru=ru, answer_ru="", used="", prio=1, status=None,
                        category_order=0, order=0)


# ---- .env ----------------------------------------------------------------

def test_dotenv_sets_but_never_overrides(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('# comment\nexport AE_T_A="quoted"\nAE_T_B=plain=with=eq\nAE_T_C=from-file\n\nbad line\n')
    monkeypatch.setenv("AE_T_C", "from-env")
    for k in ("AE_T_A", "AE_T_B"):
        monkeypatch.delenv(k, raising=False)
    load_dotenv(env)
    assert os.environ["AE_T_A"] == "quoted"
    assert os.environ["AE_T_B"] == "plain=with=eq"
    assert os.environ["AE_T_C"] == "from-env"
    for k in ("AE_T_A", "AE_T_B"):
        monkeypatch.delenv(k)
    load_dotenv(tmp_path / "missing.env")                                # no file → no-op


# ---- gateway client --------------------------------------------------------

def gateway(handler, key="k"):
    return ClaudeGateway({"claude_gateway": {"api_key": key, "base_url": "http://gw"}},
                         transport=httpx.MockTransport(handler))


def run(coro):
    return asyncio.run(coro)


def test_complete_sends_isolated_request():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"session_id": "s1", "text": "pong", "is_error": False, "cost_usd": 0.01})

    result = run(gateway(handler).complete("hi", system_prompt="sys", model="haiku"))
    assert result == GatewayResult(text="pong", cost_usd=0.01, session_id="s1")
    assert seen["auth"] == "Bearer k"
    body = seen["body"]
    assert body["tools"] == [] and body["setting_sources"] == [] and body["system_prompt"] == "sys"
    assert body["model"] == "haiku" and body["max_turns"] == 1


@pytest.mark.parametrize("handler, kind", [
    (lambda r: httpx.Response(401), "unauthorized"),
    (lambda r: httpx.Response(500, text="boom"), "failed"),
    (lambda r: httpx.Response(200, json={"text": "limit", "is_error": True}), "failed"),
])
def test_complete_error_kinds(handler, kind):
    with pytest.raises(GatewayError) as err:
        run(gateway(handler).complete("x", system_prompt="s", model="m"))
    assert err.value.kind == kind


def test_complete_504_tells_rate_limit_from_timeout():
    def paused(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"paused_until": "2026-11-13T15:00:00Z"})
        return httpx.Response(504)

    with pytest.raises(GatewayError) as err:
        run(gateway(paused).complete("x", system_prompt="s", model="m"))
    assert err.value.kind == "rate_limited" and "15:00" in str(err.value)

    def slow(request):
        return httpx.Response(200, json={"paused_until": None}) if request.url.path == "/health" else httpx.Response(504)

    with pytest.raises(GatewayError) as err:
        run(gateway(slow).complete("x", system_prompt="s", model="m"))
    assert err.value.kind == "timeout"


def test_complete_unreachable_and_not_configured():
    def refuse(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(GatewayError) as err:
        run(gateway(refuse).complete("x", system_prompt="s", model="m"))
    assert err.value.kind == "unreachable"
    with pytest.raises(GatewayError) as err:
        run(gateway(refuse, key="").complete("x", system_prompt="s", model="m"))
    assert err.value.kind == "not_configured"


# ---- translation ---------------------------------------------------------

def test_parse_reply_validates():
    batch = [q("a", "А?"), q("b", "Б?"), q("c", "В?")]
    text = 'Sure:\n```json\n{"a": " Tell me  about yourself. ", "b": "Почему?", "x": "stray"}\n```'
    assert parse_reply(text, batch) == {"a": "Tell me about yourself."}
    assert parse_reply("no json here", batch) == {}
    assert parse_reply("{broken", batch) == {}


def test_needs_translation_uses_hash():
    a, b = q("a", "один"), q("b", "два")
    cached = {"a": {"source_sha256": source_hash(a)}, "b": {"source_sha256": "old"}}
    assert [x.id for x in needs_translation([a, b, q("c", "три")], cached)] == ["b", "c"]


class FakeGateway:
    translate_model = "haiku"

    def __init__(self, fail_after=None):
        self.prompts = []
        self.fail_after = fail_after

    async def complete(self, prompt, *, system_prompt, model, effort="low", timeout_s=None):
        if self.fail_after is not None and len(self.prompts) >= self.fail_after:
            raise GatewayError("rate_limited", "paused until later")
        self.prompts.append(prompt)
        items = json.loads(prompt.split("\n", 1)[1])
        # Leave one id out to check partial results are kept.
        return GatewayResult(json.dumps({k: f"EN {k}" for k in items if k != "q3"}), 0.01, "s")


def test_translate_missing_caches_and_retries_only_missing(tmp_path):
    async def scenario():
        db = Database({"persistence": {"db_path": str(tmp_path / "t.db")}})
        await db.start()
        questions = [q(f"q{i}", f"вопрос {i}") for i in range(5)]
        gw = FakeGateway()
        stats = await translate_missing(questions, db, gw, batch_size=2)
        assert (stats.pending, stats.translated, stats.failed) == (5, 4, ["q3"])
        assert len(gw.prompts) == 3
        cached = await db.get_interview_translations()
        assert cached["q0"]["question_en"] == "EN q0" and "q3" not in cached

        gw2 = FakeGateway()
        stats = await translate_missing(questions, db, gw2)
        assert stats.pending == 1 and len(gw2.prompts) == 1             # only q3 again

        edited = [q("q0", "вопрос 0, исправленный")] + questions[1:]
        stats = await translate_missing(edited, db, FakeGateway(fail_after=0))
        assert stats.pending == 2 and stats.translated == 0 and "rate_limited" in stats.error
        await db.stop()

    asyncio.run(scenario())
