-- EPIC-10 / STORY-10-03: the questions of an interview session, in order,
-- and which question each turn belongs to (for the review and for
-- resuming at the next unanswered question).

CREATE TABLE interview_items (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    question_id TEXT NOT NULL,
    category TEXT,
    question_ru TEXT NOT NULL,
    question_en TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | asked | answered | skipped
    PRIMARY KEY (session_id, idx)
);

ALTER TABLE turns ADD COLUMN question_idx INTEGER;
