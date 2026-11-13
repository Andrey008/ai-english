"""EPIC-10 / STORY-10-02: translate prep questions RU→EN through
claude_gateway and cache them in the server DB.

    uv run python scripts/translate_prep_questions.py [--dry-run] [--show]

The server does the same in the background at start; this is for a
manual run (e.g. right after adding questions in prep). Only new or
edited questions are sent. Needs AI_ENGLISH__CLAUDE_GATEWAY__API_KEY in
server/.env and the prep container running.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.claude_gateway import ClaudeGateway  # noqa: E402
from app.config import get_config  # noqa: E402
from app.db import Database  # noqa: E402
from app.interview.prep_client import PrepClient  # noqa: E402
from app.interview.translation import needs_translation, translate_missing  # noqa: E402


async def main(dry_run: bool, show: bool) -> int:
    config = get_config()
    base = await PrepClient(config).fetch()
    db = Database(config)
    await db.start()
    try:
        cached = await db.get_interview_translations()
        todo = needs_translation(base.questions, cached)
        print(f"{len(base.questions)} questions in prep, {len(todo)} need translation")
        if dry_run:
            for q in todo:
                print(f"  {q.id}: {q.question_ru}")
            return 0
        if todo:
            stats = await translate_missing(base.questions, db, ClaudeGateway(config))
            print(f"translated {stats.translated}, failed {len(stats.failed)}, cost ${stats.cost_usd:.4f}")
            if stats.error:
                print(f"stopped: {stats.error}")
            if stats.failed:
                print("failed ids:", ", ".join(stats.failed))
        if show:
            cached = await db.get_interview_translations()
            for q in base.questions:
                print(f"\n{q.id}\n  RU: {q.question_ru}\n  EN: {(cached.get(q.id) or {}).get('question_en', '—')}")
        return 0
    finally:
        await db.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="only list what would be translated")
    parser.add_argument("--show", action="store_true", help="print every question with its translation")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.dry_run, args.show)))
