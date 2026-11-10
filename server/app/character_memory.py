"""Character memory: rolling summary generation/update (STORY-02-08).

What *the character* remembers about its relationship/history with the
user — distinct from learning-layer records (`EPIC-04`, not this
module) which are what *the system* has observed about the user's
English. See `ARCHITECTURE.md` §2.1.1.

Runs a one-shot LLM pass after a session ends — deliberately off the
real-time pipeline's latency-critical path (`ARCHITECTURE.md` §2.1's
principle for the learning layer applies equally here).

Model choice: reuses the already-warm conversational model
(`config["llm"]["model"]`, `gemma2:27b` since ADR-0012) rather than
loading a second one. Cold-loading another large model right after a
session ends, while the first is still within Ollama's keep-alive
window, is exactly the cold-load-while-resident incident pattern in
`STATUS.md`. Revisit only if a dedicated smaller model is deliberately
provisioned for this.
"""
from __future__ import annotations

import logging
from typing import Any

import ollama

logger = logging.getLogger("ai_english.character_memory")

SUMMARY_PROMPT_TEMPLATE = """You maintain {name}'s memory of an ongoing relationship with one user, across separate conversation sessions.

EXISTING MEMORY (what {name} currently remembers about the user):
{existing_summary}

NEW SESSION TRANSCRIPT:
{transcript}

Write an updated memory summary for {name}: integrate anything new from this session into the existing memory (don't just append — merge). Keep it a concise paragraph, third person, about the USER: lasting facts that matter for future conversations (name, job, family, interests, preferences, ongoing life situations, English-learning goals). Leave out one-off plans and events that will be outdated by the next conversation ("this weekend", "tomorrow"), and anything {name} promised or planned to do — {name} is a voice chat partner and can't do things in the real world. If the existing memory contains such outdated items, drop them. Output only the updated summary, nothing else.

Updated memory:"""


class CharacterMemoryService:
    def __init__(self, config: dict[str, Any], db: Any):
        self._model = config["llm"]["model"]
        self._db = db
        self._client = ollama.AsyncClient()

    async def update_after_session(self, session_id: str, character_id: str, character_name: str) -> str | None:
        transcript = await self._db.get_transcript(session_id)
        if not transcript:
            return None

        transcript_text = "\n".join(f"{turn['role']}: {turn['text']}" for turn in transcript)
        existing = await self._db.get_character_memory(character_id)
        existing_summary = (
            existing["rolling_summary"] if existing else "(no prior memory yet — this is the first session together)"
        )

        prompt = SUMMARY_PROMPT_TEMPLATE.format(
            name=character_name, existing_summary=existing_summary, transcript=transcript_text
        )
        try:
            resp = await self._client.chat(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                think=False,
            )
        except (ollama.ResponseError, ConnectionError, OSError) as exc:
            logger.warning(
                "character_memory_update_failed",
                extra={"session_id": session_id, "character_id": character_id, "error": str(exc)},
            )
            return None

        summary = resp["message"]["content"].strip()
        await self._db.upsert_character_memory(character_id, summary)
        logger.info(
            "character_memory_updated",
            extra={"session_id": session_id, "character_id": character_id},
        )
        return summary
