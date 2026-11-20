"""Build an interview for a new session (STORY-10-03): fetch the prep
base, pick the questions, attach the cached English texts."""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from app.interview.prep_client import PrepUnavailable
from app.interview.selection import NoQuestions, select_questions, weights_from_config
from app.interview.session import InterviewItem, InterviewState
from app.interview.translation import needs_translation, translate_missing

logger = logging.getLogger("ai_english.interview.builder")


class InterviewUnavailable(RuntimeError):
    """Can't start an interview; the message is fit to show the user."""


def interview_options(config: dict[str, Any], requested: Any) -> dict[str, Any]:
    """Session options: config defaults, overridden by `session_start.interview`."""
    defaults = config.get("interview") or {}
    req = requested if isinstance(requested, dict) else {}

    def int_in(value: Any, default: int, lo: int, hi: int) -> int:
        try:
            return min(hi, max(lo, int(value)))
        except (TypeError, ValueError):
            return default

    count = int_in(req.get("count"), int(defaults.get("question_count", 10)), 1, 30)
    followups = int_in(req.get("max_followups"), int(defaults.get("max_followups", 1)), 0, 3)
    categories = req.get("categories")
    categories = [str(c) for c in categories] if isinstance(categories, list) and categories else None
    return {"count": count, "max_followups": followups, "categories": categories}


async def build_interview(app, name: str, options: dict[str, Any]) -> InterviewState:
    config, db = app.state.config, app.state.db
    try:
        base = await app.state.prep_client.fetch()
    except PrepUnavailable as exc:
        raise InterviewUnavailable(str(exc)) from exc
    cached = await db.get_interview_translations()
    untranslated = {q.id for q in needs_translation(base.questions, cached)}
    if untranslated and app.state.claude_gateway.configured:
        # New/edited questions: translate in the background for next time;
        # this interview only uses ready translations.
        task = asyncio.create_task(translate_missing(base.questions, db, app.state.claude_gateway))
        app.state.background_tasks.add(task)
        task.add_done_callback(app.state.background_tasks.discard)
    ready = [q for q in base.questions if q.id not in untranslated]
    if not ready:
        raise InterviewUnavailable("no prep questions are translated yet — run scripts/translate_prep_questions.py")
    recent = await db.recent_interview_question_ids(int((config.get("interview") or {}).get("exclude_recent_sessions", 3)))
    prio_w, status_w = weights_from_config(config)
    try:
        picked = select_questions(ready, options["count"], rng=random.Random(), categories=options["categories"],
                                  exclude_ids=recent, prio_weights=prio_w, status_weights=status_w)
    except NoQuestions as exc:
        raise InterviewUnavailable(str(exc)) from exc
    items = [InterviewItem(idx=i, question_id=q.id, category=q.category, question_ru=q.question_ru,
                           question_en=cached[q.id]["question_en"]) for i, q in enumerate(picked)]
    logger.info("interview_built", extra={"count": len(items), "excluded_recent": len(recent),
                                          "untranslated": len(untranslated), "categories": options["categories"],
                                          "question_ids": [i.question_id for i in items]})
    return InterviewState(name=name, items=items, max_followups=options["max_followups"])


def state_from_rows(name: str, rows: list[dict], max_followups: int) -> InterviewState:
    items = [InterviewItem(idx=r["idx"], question_id=r["question_id"], category=r.get("category") or "",
                           question_ru=r["question_ru"], question_en=r["question_en"], status=r["status"])
             for r in rows]
    return InterviewState.resumed(name, items, max_followups)
