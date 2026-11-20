import asyncio
import json

import httpx
import numpy as np
import pytest

from bench.backends import (Delta, Done, GenParams, OllamaBackend, OpenAICompatBackend, ServerStats,
                            fold_system_prompt)
from bench.compare import conditions, table
from bench.fixture import SCRIPTS_DIR, Fixture, Turn
from bench.memory import parse_ps_rss, parse_vm_stat
from bench.metrics import measure_turn, summarize
from bench.record import to_pcm16_16k
from bench.run import inputs_digest, run_conversation, system_prompt_for


class FakeBackend:
    """Streams a reply word by word with a fixed delay; records every
    prompt it was sent."""

    kind = "fake"
    model = "fake"

    def __init__(self, reply="Hello there. How are you today?", delay=0.01, stats=None):
        self.reply, self.delay, self.stats = reply, delay, stats
        self.prompts: list[list[dict]] = []

    async def stream_chat(self, messages, params):
        self.prompts.append([dict(m) for m in messages])
        for word in self.reply.split(" "):
            await asyncio.sleep(self.delay)
            yield Delta(word + " ")
        yield Done(self.stats or ServerStats())

    async def prewarm(self, messages, params):
        self.prewarms = getattr(self, "prewarms", []) + [[dict(m) for m in messages]]

    async def aclose(self):
        pass


def small_fixture() -> Fixture:
    return Fixture(
        name="t", character_id="alex_default", english_level="B1",
        turns=[Turn("Hi!", "Hey, how's it going?"), Turn("Good, thanks.", "Glad to hear it."),
               Turn("Bye.", "See you!")],
    )


def test_scripts_load_and_build_production_prompt():
    for path in SCRIPTS_DIR.glob("*.yaml"):
        fixture = Fixture.load(path)
        assert fixture.turns and all(t.user_script and t.assistant_reference for t in fixture.turns)
        prompt = system_prompt_for(fixture)
        assert "USER'S ENGLISH LEVEL" in prompt
        assert "PAST CONVERSATIONS" not in prompt  # memory never leaks into the benchmark


def test_fixture_roundtrip_and_text_source(tmp_path):
    fixture = small_fixture()
    fixture.turns[0].audio, fixture.turns[0].user_stt = "turn01.wav", "Hi"
    fixture.save(tmp_path)
    loaded = Fixture.load(tmp_path)
    assert loaded.turns[0].user_text("stt") == "Hi"
    assert loaded.turns[1].user_text("script") == "Good, thanks."
    with pytest.raises(ValueError):
        loaded.turns[1].user_text("stt")


def test_measure_turn_timings():
    backend = FakeBackend(reply="Hello there. How are you today?", delay=0.02,
                          stats=ServerStats(prompt_tokens=50, prompt_eval_s=0.5, completion_tokens=6))
    result = asyncio.run(measure_turn(backend, [], GenParams(), turn=0, cold=True))
    assert 0.015 < result.ttft_s < result.first_sentence_s < result.total_s
    assert result.first_sentence_s < result.total_s - 0.05  # "Hello there." well before the end
    assert result.completion_tokens == 6 and result.completion_tokens_source == "server"
    assert result.prefill_tps == pytest.approx(100)
    assert result.decode_tps == pytest.approx(5 / (result.total_s - result.ttft_s))


def test_measure_turn_counts_chunks_without_server_stats():
    result = asyncio.run(measure_turn(FakeBackend(reply="One two three"), [], GenParams(), 0, False))
    assert (result.completion_tokens, result.completion_tokens_source) == (3, "chunks")
    assert result.first_sentence_s == pytest.approx(result.total_s, abs=0.01)  # no sentence end


def test_teacher_mode_sends_identical_prompts_to_every_backend():
    fixture = small_fixture()
    a, b = FakeBackend(reply="Totally different reply A."), FakeBackend(reply="Another one B.")

    async def run(backend):
        return await run_conversation(backend, fixture, "SYSTEM", GenParams(), "teacher", "script", verbose=False)

    asyncio.run(run(a))
    asyncio.run(run(b))

    def strip_tag(prompts):  # per-run cache-busting tag is the only allowed difference
        return [[{**m, "content": m["content"].split("\n", 1)[1]} if m["role"] == "system" else m
                 for m in prompt] for prompt in prompts]

    assert strip_tag(a.prompts) == strip_tag(b.prompts)
    last = a.prompts[-1]
    assert [m["content"] for m in last if m["role"] == "assistant"] == ["Hey, how's it going?", "Glad to hear it."]
    assert last[0]["content"].startswith("[benchmark run ") and last[0]["content"].endswith("SYSTEM")


def test_inputs_digest_changes_with_transcript():
    fixture = small_fixture()
    before = inputs_digest(fixture, "S", "script", None)
    fixture.turns[1].user_script = "Fine."
    assert inputs_digest(fixture, "S", "script", None) != before


def test_free_mode_keeps_own_replies_and_marks_cold_turn():
    backend = FakeBackend(reply="Mine.")
    results = asyncio.run(run_conversation(backend, small_fixture(), "S", GenParams(), "free", "script",
                                           verbose=False))
    assert [r.cold for r in results] == [True, False, False]
    assert [m["content"] for m in backend.prompts[-1] if m["role"] == "assistant"] == ["Mine. ", "Mine. "]


def test_prewarm_reply_refreshes_cache_with_own_reply_before_next_turn():
    backend = FakeBackend(reply="Mine.")
    results = asyncio.run(run_conversation(backend, small_fixture(), "S", GenParams(), "free", "script",
                                           verbose=False, prewarm_reply=True))
    assert len(backend.prewarms) == 2  # not after the last turn
    assert backend.prewarms[0][-1] == {"role": "assistant", "content": "Mine. "}
    assert backend.prompts[1][:len(backend.prewarms[0])] == backend.prewarms[0]  # next prompt extends it
    assert [r.prewarm_s is not None for r in results] == [True, True, False]


def test_each_repeat_gets_a_fresh_cache_busting_tag():
    backend = FakeBackend()

    async def twice():
        for _ in range(2):
            await run_conversation(backend, small_fixture(), "S", GenParams(), "teacher", "script", 1, verbose=False)

    asyncio.run(twice())
    assert backend.prompts[0][0]["content"] != backend.prompts[1][0]["content"]


def test_ollama_backend_maps_stream_and_stats():
    class FakeClient:
        async def chat(self, **kwargs):
            self.kwargs = kwargs

            async def gen():
                yield {"message": {"content": "Hi "}, "done": False}
                yield {"message": {"content": "there."}, "done": False}
                yield {"message": {"content": ""}, "done": True, "prompt_eval_count": 80,
                       "prompt_eval_duration": 1_600_000_000, "eval_count": 2, "eval_duration": 200_000_000}
            return gen()

    client = FakeClient()
    backend = OllamaBackend("gemma2:27b", client=client)

    async def collect():
        return [e async for e in backend.stream_chat([{"role": "user", "content": "x"}], GenParams(max_tokens=50))]

    events = asyncio.run(collect())
    assert [e.text for e in events if isinstance(e, Delta)] == ["Hi ", "there."]
    stats = events[-1].stats
    assert (stats.prompt_tokens, stats.prompt_eval_s, stats.eval_s) == (80, 1.6, 0.2)
    assert client.kwargs["options"] == {"temperature": 0.0, "seed": 42, "num_predict": 50, "num_ctx": 8192}


def test_openai_backend_parses_sse_usage_and_llama_server_timings():
    chunks = [
        {"choices": [{"delta": {"role": "assistant"}}]},
        {"choices": [{"delta": {"content": "Hi "}}]},
        {"choices": [{"delta": {"content": "there."}}]},
        {"choices": [], "usage": {"prompt_tokens": 500, "completion_tokens": 2},
         "timings": {"prompt_n": 90, "prompt_ms": 450.0, "predicted_n": 2, "predicted_ms": 180.0}},
    ]
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    backend = OpenAICompatBackend("mlx-model", transport=httpx.MockTransport(handler))

    async def collect():
        events = [e async for e in backend.stream_chat([{"role": "user", "content": "x"}], GenParams())]
        await backend.aclose()
        return events

    events = asyncio.run(collect())
    assert [e.text for e in events if isinstance(e, Delta)] == ["Hi ", "there."]
    stats = events[-1].stats
    assert (stats.prompt_tokens, stats.prompt_eval_s, stats.completion_tokens) == (90, 0.45, 2)
    assert seen["body"]["stream"] is True and seen["body"]["temperature"] == 0.0
    assert seen["body"]["max_tokens"] == GenParams.max_tokens


def test_fold_system_prompt_matches_ollama_gemma2_template():
    messages = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hey"}, {"role": "user", "content": "Bye"}]
    assert fold_system_prompt(messages) == [{"role": "user", "content": "SYS Hi"}, *messages[2:]]
    assert messages[1]["content"] == "Hi"  # input untouched
    assert fold_system_prompt(messages[1:]) == messages[1:]


VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                                  1000.
Pages active:                                 600.
Pages inactive:                               500.
Pages wired down:                             200.
Pages stored in compressor:                  9999.
Pages occupied by compressor:                 200.
"""


def test_memory_parsers():
    assert parse_vm_stat(VM_STAT) == (600 + 200 + 200) * 16384 / 2**20
    ps = ("11  2048 /opt/ollama/llama-server --model x\n"
          "12  1024 /usr/bin/python -m mlx_lm.server\n"
          "13   512 zsh\n"
          "99  4096 python -m bench.run x --process-pattern llama-server\n")
    assert parse_ps_rss(ps, r"llama-server", frozenset({99})) == 2.0
    assert parse_ps_rss(ps, r"mlx_lm\.server|llama-server", frozenset({99})) == 3.0


def test_summarize():
    s = summarize([3.0, 1.0, None, 2.0, 10.0])
    assert s["n"] == 4 and s["median"] == 2.5 and s["p90"] == 10.0
    assert summarize([None]) is None


def _report(label, ttft_warm, params=None):
    turns = [{"turn": 0, "cold": True, "ttft_s": 5.0, "first_sentence_s": 6.0, "decode_tps": 9.0,
              "prefill_tps": None, "reply": "a"}] + [
        {"turn": i, "cold": False, "ttft_s": ttft_warm, "first_sentence_s": ttft_warm + 0.5,
         "decode_tps": 9.0, "prefill_tps": 60.0, "reply": "b"} for i in (1, 2)]
    return {"label": label, "fixture": "f", "mode": "teacher", "text_source": "stt",
            "params": params or {"max_tokens": 160}, "machine": {"chip": "M4 Pro"},
            "memory": {"peak_rss_mb": 20480, "peak_system_delta_mb": None}, "runs": [{"turns": turns}]}


def test_compare_table_shows_change_vs_baseline():
    out = table([_report("ollama", 2.0), _report("mlx", 1.0)])
    assert "| ollama | 5.00 | 2.00 |" in out
    assert "1.00 (-50% ✓)" in out
    assert "20.0" in out


def test_compare_flags_unequal_conditions():
    assert conditions([_report("a", 1.0), _report("b", 1.0)]) == []
    changed = {**_report("b", 1.0), "inputs_sha256": "other"}
    assert any("inputs_sha256" in w for w in conditions([_report("a", 1.0), changed]))
    warnings = conditions([_report("a", 1.0), _report("b", 1.0, params={"max_tokens": 50})])
    assert any("params" in w for w in warnings)


def test_recording_resampled_to_16k_pcm16():
    pcm = to_pcm16_16k(np.zeros(48000, dtype=np.float32), 48000)  # 1s at 48kHz
    assert len(pcm) == 16000 * 2
