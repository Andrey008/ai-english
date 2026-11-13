-- EPIC-10 / ADR-0016 §4: English versions of prep questions (the base is
-- Russian), made once through claude_gateway. source_sha256 is the hash
-- of the Russian text: an edit in prep makes the row stale.

CREATE TABLE interview_translations (
    question_id TEXT PRIMARY KEY,
    source_sha256 TEXT NOT NULL,
    question_en TEXT NOT NULL,
    model TEXT,
    created_at TEXT NOT NULL
);
