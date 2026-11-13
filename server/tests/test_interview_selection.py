import asyncio
import random
from collections import Counter

import httpx
import pytest

from app.interview.prep_client import PrepClient, PrepQuestion, PrepUnavailable, parse_export
from app.interview.selection import NoQuestions, select_questions, weights_from_config

EXPORT = {
    "exported": "2026-11-13T13:54:49",
    "categories": [
        {"id": "about", "title": "О себе", "group": "Ты", "order": 101, "questions": [
            {"id": "about-pitch", "cat": "about", "prio": 1, "q": "Расскажи о себе", "a": "Черновик", "used": "",
             "order": 10, "status": None},
            {"id": "about-empty", "cat": "about", "prio": 1, "q": "  ", "a": ""},
        ]},
        {"id": "api", "title": "API", "group": "Архитектура", "order": 501, "questions": [
            {"id": "api-rest", "cat": "api", "prio": "2", "q": "REST vs GraphQL?", "a": "...", "order": 5,
             "status": "learn"},
            {"id": "api-odd", "cat": "api", "prio": 7, "q": "Странный prio", "status": "bogus"},
        ]},
    ],
    "uncategorized": [{"id": "orphan", "cat": "", "prio": 3, "q": "Без категории"}],
}


def q(id_, prio=2, status=None, cat="c", cat_order=0, order=0):
    return PrepQuestion(id=id_, category=cat, question_ru=id_, answer_ru="", used="", prio=prio, status=status,
                        category_order=cat_order, order=order)


def test_parse_export_normalises_fields():
    base = parse_export(EXPORT)
    ids = [x.id for x in base.questions]
    assert ids == ["about-pitch", "api-rest", "api-odd", "orphan"]       # empty question dropped
    rest = base.question("api-rest")
    assert rest.prio == 2 and rest.status == "learn" and rest.category_order == 501
    odd = base.question("api-odd")
    assert odd.prio == 2 and odd.status is None                          # out-of-range → defaults
    assert [c.id for c in base.categories] == ["about", "api"]


def test_parse_export_rejects_wrong_shape():
    with pytest.raises(PrepUnavailable):
        parse_export({"questions": []})


def test_client_fetches_and_reports_errors():
    ok = httpx.MockTransport(lambda r: httpx.Response(200, json=EXPORT))
    base = asyncio.run(PrepClient({"interview": {"prep": {"base_url": "http://prep"}}}, transport=ok).fetch())
    assert len(base.questions) == 4

    def refuse(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(PrepUnavailable, match="not reachable"):
        asyncio.run(PrepClient({}, transport=httpx.MockTransport(refuse)).fetch())
    with pytest.raises(PrepUnavailable, match="500"):
        asyncio.run(PrepClient({}, transport=httpx.MockTransport(lambda r: httpx.Response(500))).fetch())
    with pytest.raises(PrepUnavailable, match="invalid JSON"):
        asyncio.run(PrepClient({}, transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>"))).fetch())


def test_selects_distinct_and_orders_by_category():
    pool = [q(f"q{i}", cat=f"c{i % 3}", cat_order=i % 3, order=i) for i in range(30)]
    picked = select_questions(pool, 10, rng=random.Random(1))
    assert len(picked) == 10 and len({p.id for p in picked}) == 10
    assert [p.category_order for p in picked] == sorted(p.category_order for p in picked)


def test_weights_shift_distribution():
    pool = [q("often", prio=1, status="learn"), q("rare", prio=3, status="know")] + [q(f"m{i}") for i in range(8)]
    counts = Counter()
    rng = random.Random(7)
    for _ in range(2000):
        counts.update(p.id for p in select_questions(pool, 3, rng=rng))
    assert counts["often"] > 2 * counts["m0"] > 2 * counts["rare"]


def test_exclusion_and_relaxation():
    pool = [q(f"q{i}") for i in range(5)]
    picked = select_questions(pool, 3, rng=random.Random(2), exclude_ids={"q0", "q1"})
    assert {p.id for p in picked} == {"q2", "q3", "q4"}
    picked = select_questions(pool, 5, rng=random.Random(2), exclude_ids={"q0", "q1", "q2"})
    assert len(picked) == 5                                             # recent ones allowed back in


def test_category_filter_and_empty():
    pool = [q("a1", cat="a"), q("b1", cat="b")]
    assert [p.id for p in select_questions(pool, 5, categories={"b"})] == ["b1"]
    with pytest.raises(NoQuestions):
        select_questions(pool, 5, categories={"zzz"})
    with pytest.raises(NoQuestions):
        select_questions([], 5)


def test_weights_from_config_yaml_shape():
    prio, status = weights_from_config({"interview": {"weights": {"prio": {1: 3, "2": "2"}, "status": {"know": 0}}}})
    assert prio == {1: 3.0, 2: 2.0} and status == {"know": 0.0}
    assert weights_from_config({})[0][1] == 3.0
