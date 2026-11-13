"""SQLite persistence (STORY-02-06): sessions/turns, per ARCHITECTURE.md
§3.2 (ADR-0002). Migrations are numbered `.sql` files in `/migrations`,
applied once each, tracked in `schema_migrations` — lightweight, no
framework, appropriate for a single-user single-file DB.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from app.config import resolve_repo_path

logger = logging.getLogger("ai_english.db")

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, config: dict[str, Any]):
        self._path = resolve_repo_path(config["persistence"]["db_path"])
        self._conn: aiosqlite.Connection | None = None

    async def start(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self._path))
        self._conn.row_factory = aiosqlite.Row
        await self._apply_migrations()
        logger.info("db_ready", extra={"path": str(self._path)})

    async def stop(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def _apply_migrations(self) -> None:
        assert self._conn is not None
        await self._conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (filename TEXT PRIMARY KEY, applied_at TEXT)"
        )
        await self._conn.commit()
        cursor = await self._conn.execute("SELECT filename FROM schema_migrations")
        applied = {row["filename"] for row in await cursor.fetchall()}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in applied:
                continue
            await self._conn.executescript(path.read_text())
            await self._conn.execute(
                "INSERT INTO schema_migrations (filename, applied_at) VALUES (?, ?)",
                (path.name, _now()),
            )
            await self._conn.commit()
            logger.info("migration_applied", extra={"migration_file": path.name})

    async def create_session(
        self,
        session_id: str,
        character_id: str | None = None,
        scenario_id: str | None = None,
        english_level: str | None = None,
        use_memory: bool = True,
    ) -> None:
        """Upsert, not a plain insert: `SessionRegistry.try_claim` reuses
        the client-requested `session_id` even for a brand-new session
        (e.g. reconnecting after a server restart, once the in-memory
        registry — but not this SQLite table — has forgotten it, per
        `ws_session.py`'s "known gap" doc). A plain INSERT then hits this
        table's still-persisted row for that id and crashes with a UNIQUE
        constraint violation. Found live during `STORY-05-05`'s Android
        client reconnect verification. Upserting starts the row fresh
        (clears `ended_at`, updates the rest) exactly like a real new
        session should look, whether or not that id happens to be reused.
        (Since ADR-0015 such a reconnect resumes the existing row instead,
        so the conflict branch is a fallback only.)
        """
        assert self._conn is not None
        await self._conn.execute(
            """
            INSERT INTO sessions (id, character_id, started_at, ended_at, scenario_id, english_level, use_memory)
            VALUES (?, ?, ?, NULL, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                character_id = excluded.character_id,
                started_at = excluded.started_at,
                ended_at = NULL,
                scenario_id = excluded.scenario_id,
                english_level = excluded.english_level,
                use_memory = excluded.use_memory
            """,
            (session_id, character_id, _now(), scenario_id, english_level, int(use_memory)),
        )
        await self._conn.commit()

    async def reopen_session(self, session_id: str) -> None:
        """A resumed conversation (ADR-0015) is live again until its next end."""
        assert self._conn is not None
        await self._conn.execute("UPDATE sessions SET ended_at = NULL WHERE id = ?", (session_id,))
        await self._conn.commit()

    async def end_session(self, session_id: str) -> None:
        assert self._conn is not None
        await self._conn.execute(
            "UPDATE sessions SET ended_at = ? WHERE id = ?", (_now(), session_id)
        )
        await self._conn.commit()

    async def add_turn(self, session_id: str, role: str, text: str, audio_ref: str | None = None) -> None:
        assert self._conn is not None
        await self._conn.execute(
            "INSERT INTO turns (id, session_id, role, text, audio_ref, ts) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), session_id, role, text, audio_ref, _now()),
        )
        await self._conn.commit()

    async def get_transcript(self, session_id: str, since: str | None = None) -> list[dict]:
        """`since` (an ISO timestamp) limits it to turns after that moment."""
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT role, text, ts FROM turns WHERE session_id = ? AND ts > ? ORDER BY ts ASC",
            (session_id, since or ""),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def list_conversations(self) -> list[dict]:
        """Sessions with at least one user turn, most recently active first.
        `topic` is the first user line, for rows without a wrap-up title."""
        assert self._conn is not None
        cursor = await self._conn.execute(
            """
            SELECT s.id, s.character_id, s.scenario_id, s.english_level, s.started_at, s.ended_at, s.title,
                   COUNT(t.id) AS turns,
                   SUM(t.role = 'user') AS user_turns,
                   MAX(t.ts) AS last_turn_at,
                   (SELECT u.text FROM turns u WHERE u.session_id = s.id AND u.role = 'user'
                    ORDER BY u.ts LIMIT 1) AS topic
            FROM sessions s JOIN turns t ON t.session_id = s.id
            GROUP BY s.id
            HAVING user_turns > 0
            ORDER BY last_turn_at DESC
            """
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def save_wrap_up(self, session_id: str, title: str | None, summary: str | None, summary_turns: int) -> None:
        """A new title replaces the old one unless the user set it by hand;
        a summary is only written when there is one."""
        assert self._conn is not None
        new_title = "CASE WHEN title_edited THEN title ELSE COALESCE(?, title) END"
        if summary:
            await self._conn.execute(
                f"UPDATE sessions SET title = {new_title}, summary = ?, summary_turns = ? WHERE id = ?",
                (title, summary, summary_turns, session_id),
            )
        else:
            await self._conn.execute(f"UPDATE sessions SET title = {new_title} WHERE id = ?", (title, session_id))
        await self._conn.commit()

    async def rename_session(self, session_id: str, title: str) -> bool:
        assert self._conn is not None
        cursor = await self._conn.execute("UPDATE sessions SET title = ?, title_edited = 1 WHERE id = ?", (title, session_id))
        await self._conn.commit()
        return cursor.rowcount > 0

    async def delete_session(self, session_id: str) -> bool:
        assert self._conn is not None
        await self._conn.execute("DELETE FROM turns WHERE session_id = ?", (session_id,))
        cursor = await self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        await self._conn.commit()
        return cursor.rowcount > 0

    async def get_session(self, session_id: str) -> dict | None:
        assert self._conn is not None
        cursor = await self._conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_character_memory(self, character_id: str) -> dict | None:
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT * FROM character_memory WHERE character_id = ?", (character_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def upsert_character_memory(self, character_id: str, rolling_summary: str) -> None:
        assert self._conn is not None
        await self._conn.execute(
            """
            INSERT INTO character_memory (character_id, rolling_summary, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(character_id) DO UPDATE SET rolling_summary = excluded.rolling_summary, updated_at = excluded.updated_at
            """,
            (character_id, rolling_summary, _now()),
        )
        await self._conn.commit()

    async def delete_character_memory(self, character_id: str) -> None:
        assert self._conn is not None
        await self._conn.execute("DELETE FROM character_memory WHERE character_id = ?", (character_id,))
        await self._conn.commit()

    async def get_interview_translations(self) -> dict[str, dict]:
        """question_id → {source_sha256, question_en}."""
        assert self._conn is not None
        cursor = await self._conn.execute("SELECT question_id, source_sha256, question_en FROM interview_translations")
        return {row["question_id"]: dict(row) for row in await cursor.fetchall()}

    async def save_interview_translations(self, rows: list[tuple[str, str, str]], model: str) -> None:
        """rows: (question_id, source_sha256, question_en); upsert."""
        assert self._conn is not None
        now = _now()
        await self._conn.executemany(
            """
            INSERT INTO interview_translations (question_id, source_sha256, question_en, model, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(question_id) DO UPDATE SET source_sha256 = excluded.source_sha256,
                question_en = excluded.question_en, model = excluded.model, created_at = excluded.created_at
            """,
            [(qid, sha, text, model, now) for qid, sha, text in rows],
        )
        await self._conn.commit()
