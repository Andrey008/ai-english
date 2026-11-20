-- ADR-0017: per-device API tokens. Only the SHA-256 of a token is stored;
-- the token itself is shown once, by `scripts/devices.py create`.

CREATE TABLE devices (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT
);
