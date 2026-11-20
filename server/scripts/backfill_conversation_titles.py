"""One-off (AE-4 / ADR-0015): wrap-up titles, and notes for long ones, for
conversations that ended before the server wrote them itself.

    uv run python scripts/backfill_conversation_titles.py [--dry-run]

Uses the shared Ollama: each conversation is prefilled cold (~10-20s), so
don't run it during a voice session. Skips rows that already have a title.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_config  # noqa: E402
from app.conversation_engine import ConversationEngine, turns_to_messages  # noqa: E402
from app.db import Database  # noqa: E402
from app.persona import DEFAULT_ENGLISH_LEVEL  # noqa: E402
from app.presets import PresetStore  # noqa: E402
from app.scenarios import ScenarioStore  # noqa: E402
from app.ws_session import compose_system_prompt  # noqa: E402


async def main(dry_run: bool) -> None:
    config = get_config()
    db, engine = Database(config), ConversationEngine(config)
    presets, scenarios = PresetStore(config), ScenarioStore(config)
    await db.start()
    try:
        for row in await db.list_conversations():
            if row["title"]:
                continue
            session = await db.get_session(row["id"])
            preset = presets.get(row["character_id"]) if row["character_id"] else None
            scenario = scenarios.get(row["scenario_id"]) if row["scenario_id"] else None
            system = compose_system_prompt(preset, scenario, session.get("english_level") or DEFAULT_ENGLISH_LEVEL, None)
            turns = await db.get_transcript(row["id"])
            messages = [{"role": "system", "content": system}] + turns_to_messages(turns)
            with_notes = not engine.fits_context(messages)
            if dry_run:
                print(row["id"][:8], len(turns), "turns", "notes" if with_notes else "title")
                continue
            title, notes = await engine.wrap_up(row["id"], messages, with_notes)
            if title or notes:
                await db.save_wrap_up(row["id"], title, notes, len(turns))
            print(row["id"][:8], title, f"(+{len(notes.split())} words of notes)" if notes else "")
    finally:
        await db.stop()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    asyncio.run(main(ap.parse_args().dry_run))
