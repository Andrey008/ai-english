"""Config loading: models_config/default.yaml, overridable via env vars.

Env var override scheme: `AI_ENGLISH__<SECTION>__<KEY>` (double underscore
nesting), e.g. `AI_ENGLISH__LLM__MODEL=gemma2:27b`. Point at a different
base file entirely with `AI_ENGLISH_CONFIG_FILE=/path/to.yaml`.

Secrets (e.g. `AI_ENGLISH__CLAUDE_GATEWAY__API_KEY`) go in `server/.env`
(gitignored), never in the YAML. It is read into the environment at load
time; variables already set in the real environment win.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

SERVER_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SERVER_DIR.parent
DEFAULT_CONFIG_PATH = SERVER_DIR / "models_config" / "default.yaml"
ENV_PREFIX = "AI_ENGLISH__"
DOTENV_PATH = SERVER_DIR / ".env"


def resolve_repo_path(relative_path: str) -> Path:
    """Resolve a config path (given relative to the repo root) to absolute."""
    return (REPO_ROOT / relative_path).resolve()


def load_dotenv(path: Path = DOTENV_PATH) -> None:
    """Minimal `.env` reader: `KEY=VALUE` lines, `#` comments, optional
    `export ` prefix and surrounding quotes. Never overrides a variable
    that is already set."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def _apply_env_overrides(config: dict[str, Any]) -> dict[str, Any]:
    for env_key, value in os.environ.items():
        if not env_key.startswith(ENV_PREFIX):
            continue
        path = env_key[len(ENV_PREFIX):].lower().split("__")
        node = config
        for part in path[:-1]:
            node = node.setdefault(part, {})
        node[path[-1]] = value
    return config


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    load_dotenv()
    config_path = Path(path or os.environ.get("AI_ENGLISH_CONFIG_FILE") or DEFAULT_CONFIG_PATH)
    with config_path.open() as f:
        config = yaml.safe_load(f) or {}
    return _apply_env_overrides(config)


@lru_cache
def get_config() -> dict[str, Any]:
    return load_config()
