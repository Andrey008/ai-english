"""RU→EN translation cache for prep questions (STORY-10-02, ADR-0016 §4).

Questions are translated once through claude_gateway, in batches, and
stored keyed by question id + a hash of the Russian text. Runs in the
background (server start, or `scripts/translate_prep_questions.py`),
never during a session start.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field

from app.claude_gateway import ClaudeGateway, GatewayError
from app.interview.prep_client import PrepQuestion

logger = logging.getLogger("ai_english.interview.translation")

SYSTEM_PROMPT = """\
You translate Russian job-interview questions into natural spoken English.
The English text is read aloud by a senior engineer interviewing a backend
developer, so it must sound like something a person says, not a written
title. Rules:
- Address the candidate as "you". Keep it to one or two short sentences.
- Keep product, technology and company names as they are (Magento,
  Shopify, GraphQL, Rezolve, ...).
- Turn notes in brackets into speech, e.g. "Расскажи о себе (1–2 минуты)"
  → "Could you tell me about yourself? A minute or two is fine."
- No Russian words, no markdown, no quotes around the text.
Reply with one JSON object only, mapping each given id to its English
text, e.g. {"q-1": "...", "q-2": "..."}. No other text."""

_CYRILLIC = re.compile(r"[А-Яа-яЁёІіЇїЄєҐґ]")
_JSON_OBJECT = re.compile(r"\{.*\}", re.S)


def source_hash(question: PrepQuestion) -> str:
    return hashlib.sha256(question.question_ru.encode()).hexdigest()


def needs_translation(questions: list[PrepQuestion], cached: dict[str, dict]) -> list[PrepQuestion]:
    return [q for q in questions
            if (row := cached.get(q.id)) is None or row.get("source_sha256") != source_hash(q)]


def build_prompt(batch: list[PrepQuestion]) -> str:
    items = {q.id: q.question_ru for q in batch}
    return "Translate these questions:\n" + json.dumps(items, ensure_ascii=False, indent=1)


def parse_reply(text: str, batch: list[PrepQuestion]) -> dict[str, str]:
    """Valid translations only: known id, non-empty, no Cyrillic left."""
    match = _JSON_OBJECT.search(text or "")
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return {}
    wanted = {q.id for q in batch}
    out = {}
    for qid, value in (data.items() if isinstance(data, dict) else []):
        value = " ".join(str(value).split()).strip(' "')
        if qid in wanted and value and not _CYRILLIC.search(value):
            out[qid] = value
    return out


@dataclass
class TranslationStats:
    total: int = 0
    pending: int = 0
    translated: int = 0
    failed: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    error: str | None = None


async def translate_missing(questions: list[PrepQuestion], db, gateway: ClaudeGateway,
                            batch_size: int = 20) -> TranslationStats:
    cached = await db.get_interview_translations()
    todo = needs_translation(questions, cached)
    stats = TranslationStats(total=len(questions), pending=len(todo))
    for start in range(0, len(todo), batch_size):
        batch = todo[start:start + batch_size]
        try:
            result = await gateway.complete(build_prompt(batch), system_prompt=SYSTEM_PROMPT,
                                            model=gateway.translate_model, timeout_s=300)
        except GatewayError as exc:
            # Unreachable / rate-limited: stop; the rest is retried next run.
            stats.error = f"{exc.kind}: {exc}"
            stats.failed += [q.id for q in todo[start:]]
            logger.warning("interview_translation_stopped", extra={"error": stats.error})
            break
        stats.cost_usd += result.cost_usd or 0.0
        done = parse_reply(result.text, batch)
        by_id = {q.id: q for q in batch}
        await db.save_interview_translations(
            [(qid, source_hash(by_id[qid]), text) for qid, text in done.items()], gateway.translate_model)
        stats.translated += len(done)
        stats.failed += [q.id for q in batch if q.id not in done]
    logger.info("interview_translation_done", extra={
        "total": stats.total, "pending": stats.pending, "translated": stats.translated,
        "failed": len(stats.failed), "cost_usd": round(stats.cost_usd, 4)})
    return stats
