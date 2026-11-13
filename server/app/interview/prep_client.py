"""Read-only client for the prep base (STORY-10-01, ADR-0016 §3).

The prep service exposes its whole base as one JSON document
(`GET /export.json`). Its MCP tools return Markdown for LLMs; this server
needs structured fields, and the base is small, so it reads the export.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger("ai_english.interview.prep")


class PrepUnavailable(RuntimeError):
    """The prep base can't be read; the message is fit to show the user."""


@dataclass(frozen=True)
class PrepCategory:
    id: str
    title: str
    group: str
    order: int


@dataclass(frozen=True)
class PrepQuestion:
    id: str
    category: str
    question_ru: str
    answer_ru: str
    used: str
    prio: int
    status: str | None   # "know" | "learn" | None
    category_order: int
    order: int


@dataclass(frozen=True)
class PrepBase:
    categories: list[PrepCategory]
    questions: list[PrepQuestion]

    def question(self, question_id: str) -> PrepQuestion | None:
        return next((q for q in self.questions if q.id == question_id), None)


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_export(doc: dict[str, Any]) -> PrepBase:
    """`/export.json` → PrepBase. Unknown/missing fields get defaults;
    questions without text are dropped."""
    if not isinstance(doc, dict) or not isinstance(doc.get("categories"), list):
        raise PrepUnavailable("prep export has an unexpected format (no 'categories' list)")
    categories: list[PrepCategory] = []
    questions: list[PrepQuestion] = []

    def add_questions(items: Any, category_order: int) -> None:
        for raw in items or []:
            if not isinstance(raw, dict) or not raw.get("id") or not str(raw.get("q") or "").strip():
                continue
            prio = _int(raw.get("prio"), 2)
            status = raw.get("status") if raw.get("status") in ("know", "learn") else None
            questions.append(PrepQuestion(
                id=str(raw["id"]),
                category=str(raw.get("cat") or ""),
                question_ru=str(raw["q"]).strip(),
                answer_ru=str(raw.get("a") or ""),
                used=str(raw.get("used") or ""),
                prio=prio if prio in (1, 2, 3) else 2,
                status=status,
                category_order=category_order,
                order=_int(raw.get("order"), 0),
            ))

    for raw_cat in doc["categories"]:
        if not isinstance(raw_cat, dict) or not raw_cat.get("id"):
            continue
        order = _int(raw_cat.get("order"), 0)
        categories.append(PrepCategory(
            id=str(raw_cat["id"]), title=str(raw_cat.get("title") or raw_cat["id"]),
            group=str(raw_cat.get("group") or ""), order=order,
        ))
        add_questions(raw_cat.get("questions"), order)
    add_questions(doc.get("uncategorized"), 10**6)
    return PrepBase(categories=categories, questions=questions)


class PrepClient:
    def __init__(self, config: dict[str, Any], transport: httpx.AsyncBaseTransport | None = None):
        prep = (config.get("interview") or {}).get("prep") or {}
        self._base_url = str(prep.get("base_url") or "http://127.0.0.1").rstrip("/")
        self._timeout = float(prep.get("timeout_s") or 3)
        self._transport = transport

    async def fetch(self) -> PrepBase:
        url = f"{self._base_url}/export.json"
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.get(url)
                response.raise_for_status()
                doc = response.json()
        except httpx.HTTPStatusError as exc:
            raise PrepUnavailable(f"prep base answered {exc.response.status_code} at {url}") from exc
        except httpx.HTTPError as exc:
            raise PrepUnavailable(f"prep base is not reachable at {url} — is its Docker container running?") from exc
        except ValueError as exc:
            raise PrepUnavailable(f"prep base returned invalid JSON at {url}") from exc
        base = parse_export(doc)
        logger.info("prep_fetched", extra={"questions": len(base.questions), "categories": len(base.categories)})
        return base
