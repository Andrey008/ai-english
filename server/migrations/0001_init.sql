-- STORY-02-06: sessions/turns schema, per ARCHITECTURE.md §3.2 / ADR-0002.

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    character_id TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    scenario_id TEXT
);

CREATE TABLE IF NOT EXISTS turns (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    audio_ref TEXT,
    ts TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_turns_session_id ON turns(session_id);
