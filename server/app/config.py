"""Config loading: models_config/default.yaml, overridable via env vars.

Env var override scheme: `AI_ENGLISH__<SECTION>__<KEY>` (double underscore
nesting), e.g. `AI_ENGLISH__LLM__MODEL=gemma2:27b`. Point at a different
base file entirely with `AI_ENGLISH_CONFIG_FILE=/path/to.yaml`.
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


def resolve_repo_path(relative_path: str) -> Path:
    """Resolve a config path (given relative to the repo root) to absolute."""
    return (REPO_ROOT / relative_path).resolve()


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
    config_path = Path(path or os.environ.get("AI_ENGLISH_CONFIG_FILE") or DEFAULT_CONFIG_PATH)
    with config_path.open() as f:
        config = yaml.safe_load(f) or {}
    return _apply_env_overrides(config)


@lru_cache
def get_config() -> dict[str, Any]:
    return load_config()
