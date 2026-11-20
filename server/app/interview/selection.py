"""Weighted random choice of interview questions (STORY-10-01).

Pure and seedable. Questions marked "learn" and frequently asked ones
(prio 1) come up more often; "know" ones less; ones asked in recent
interviews are skipped unless that leaves too few.
"""
from __future__ import annotations

import random
from collections.abc import Collection
from typing import Any

from app.interview.prep_client import PrepQuestion

DEFAULT_PRIO_WEIGHTS = {1: 3.0, 2: 2.0, 3: 1.0}
DEFAULT_STATUS_WEIGHTS = {"learn": 2.0, "none": 1.0, "know": 0.5}


class NoQuestions(ValueError):
    pass


def weights_from_config(config: dict[str, Any]) -> tuple[dict[int, float], dict[str, float]]:
    weights = (config.get("interview") or {}).get("weights") or {}
    prio = {int(k): float(v) for k, v in (weights.get("prio") or DEFAULT_PRIO_WEIGHTS).items()}
    status = {str(k): float(v) for k, v in (weights.get("status") or DEFAULT_STATUS_WEIGHTS).items()}
    return prio, status


def question_weight(q: PrepQuestion, prio_w: dict[int, float], status_w: dict[str, float]) -> float:
    return prio_w.get(q.prio, 1.0) * status_w.get(q.status or "none", 1.0)


def _weighted_sample(pool: list[PrepQuestion], k: int, rng: random.Random,
                     prio_w: dict[int, float], status_w: dict[str, float]) -> list[PrepQuestion]:
    # Efraimidis–Spirakis: key = u^(1/w), keep the k largest. Zero weight = never.
    keyed = []
    for q in pool:
        w = question_weight(q, prio_w, status_w)
        if w > 0:
            keyed.append((rng.random() ** (1.0 / w), q))
    keyed.sort(key=lambda kq: kq[0], reverse=True)
    return [q for _, q in keyed[:k]]


def select_questions(
    questions: list[PrepQuestion],
    count: int,
    *,
    rng: random.Random | None = None,
    categories: Collection[str] | None = None,
    exclude_ids: Collection[str] = (),
    prio_weights: dict[int, float] | None = None,
    status_weights: dict[str, float] | None = None,
) -> list[PrepQuestion]:
    """Pick up to `count` distinct questions, then order them the way the
    prep base orders categories (about → projects → … → technical), so the
    interview flows like a real one instead of jumping between topics."""
    rng = rng or random.Random()
    prio_w = prio_weights or DEFAULT_PRIO_WEIGHTS
    status_w = status_weights or DEFAULT_STATUS_WEIGHTS
    pool = [q for q in questions if not categories or q.category in categories]
    if not pool:
        raise NoQuestions("no questions in the prep base" + (" for the chosen categories" if categories else ""))
    excluded = set(exclude_ids)
    fresh = [q for q in pool if q.id not in excluded]
    picked = _weighted_sample(fresh, count, rng, prio_w, status_w)
    if len(picked) < count:
        # Not enough fresh ones: allow recently asked questions again.
        recent = [q for q in pool if q.id in excluded]
        picked += _weighted_sample(recent, count - len(picked), rng, prio_w, status_w)
    if not picked:
        raise NoQuestions("every question in the pool has weight 0")
    return sorted(picked, key=lambda q: (q.category_order, q.order, q.id))
