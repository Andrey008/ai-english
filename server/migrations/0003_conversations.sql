-- AE-4 / ADR-0015: a sessions row is a conversation that can be resumed.
-- english_level/use_memory restore the session settings; title/summary
-- are written by the wrap-up after a clean end (summary_turns = how many
-- turns the summary covers).

ALTER TABLE sessions ADD COLUMN english_level TEXT;
ALTER TABLE sessions ADD COLUMN use_memory INTEGER;
ALTER TABLE sessions ADD COLUMN title TEXT;
ALTER TABLE sessions ADD COLUMN summary TEXT;
ALTER TABLE sessions ADD COLUMN summary_turns INTEGER;
