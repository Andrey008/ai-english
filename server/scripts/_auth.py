"""Auth header for the live-check scripts (ADR-0017).

Set `AI_ENGLISH_TOKEN` to a token from `scripts/devices.py create`, e.g.
in `server/.env` (gitignored) — the scripts read it from there too.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_dotenv  # noqa: E402


def auth_headers() -> dict[str, str]:
    load_dotenv()
    token = os.environ.get("AI_ENGLISH_TOKEN", "").strip()
    if not token:
        print("warning: AI_ENGLISH_TOKEN is not set — the server will answer 401", file=sys.stderr)
        return {}
    return {"Authorization": f"Bearer {token}"}
