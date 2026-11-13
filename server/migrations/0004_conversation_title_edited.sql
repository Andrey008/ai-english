-- AE-4: a title the user set by hand; the wrap-up no longer overwrites it.

ALTER TABLE sessions ADD COLUMN title_edited INTEGER NOT NULL DEFAULT 0;
