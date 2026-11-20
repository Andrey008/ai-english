-- AE-5: words the user didn't understand in a conversation, collected for
-- learning elsewhere (EnglishDom). Filled by a post-session pass
-- (`app/vocabulary.py`), never on the live path.

CREATE TABLE vocabulary (
    id TEXT PRIMARY KEY,
    word TEXT NOT NULL,
    word_key TEXT NOT NULL UNIQUE,      -- lowercased, whitespace-collapsed: one row per word
    context TEXT,                       -- the character's sentence it was heard in
    explanation TEXT,                   -- short plain-English meaning
    translation_ru TEXT,
    source TEXT NOT NULL,               -- asked | bookmark
    session_id TEXT,                    -- where it was last heard; kept if that conversation is deleted
    status TEXT NOT NULL DEFAULT 'new', -- new | added | dismissed
    times_seen INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

-- Moments the user marked with the bookmark button during a conversation.
CREATE TABLE bookmarks (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    ts TEXT NOT NULL
);
CREATE INDEX bookmarks_session ON bookmarks (session_id, ts);

-- Watermark: the newest turn the vocabulary pass has already looked at, so
-- each visit of a resumed conversation is analysed once and only its new
-- turns are read. Existing conversations start fully scanned — the pass
-- must not dig through old history.
ALTER TABLE sessions ADD COLUMN vocab_scanned_until TEXT;
UPDATE sessions SET vocab_scanned_until = (SELECT MAX(ts) FROM turns WHERE turns.session_id = sessions.id);
