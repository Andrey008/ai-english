-- STORY-02-08: per-character rolling memory, per ARCHITECTURE.md §3.2/§2.1.1.
-- Distinct from learning-layer records (EPIC-04) — this is what the
-- character remembers, not what the system has observed about the user.

CREATE TABLE IF NOT EXISTS character_memory (
    character_id TEXT PRIMARY KEY,
    rolling_summary TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
