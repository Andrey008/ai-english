"""Scenario definition manager (STORY-03-03): CRUD over JSON scenarios on
disk, per `ARCHITECTURE.md` §3.3's schema. Mirrors `presets.py`'s
`PresetStore` pattern exactly — same file-per-id storage, same
create/get/list/update/delete shape, same fail-fast-at-write-time
validation via Pydantic. No seed scenario here (content is `STORY-03-05`'s
job); an empty store is a valid, working state (freeform-only).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.config import resolve_repo_path


class ScenarioDefinition(BaseModel):
    id: str
    title: str
    difficulty: int = Field(ge=1, le=5)
    character_role_prompt_addendum: str
    goal: str
    opening_line_hint: str


class ScenarioError(RuntimeError):
    pass


class ScenarioExistsError(ScenarioError):
    pass


class ScenarioNotFoundError(ScenarioError):
    pass


class ScenarioStore:
    def __init__(self, config: dict[str, Any]):
        self._dir: Path = resolve_repo_path(config["scenarios"]["dir"])
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, scenario_id: str) -> Path:
        return self._dir / f"{scenario_id}.json"

    def create(self, scenario: ScenarioDefinition) -> ScenarioDefinition:
        path = self._path(scenario.id)
        if path.exists():
            raise ScenarioExistsError(f"scenario {scenario.id!r} already exists")
        path.write_text(scenario.model_dump_json(indent=2))
        return scenario

    def get(self, scenario_id: str) -> ScenarioDefinition | None:
        path = self._path(scenario_id)
        if not path.exists():
            return None
        return ScenarioDefinition.model_validate_json(path.read_text())

    def list(self) -> list[ScenarioDefinition]:
        return [
            ScenarioDefinition.model_validate_json(p.read_text())
            for p in sorted(self._dir.glob("*.json"))
        ]

    def update(self, scenario_id: str, scenario: ScenarioDefinition) -> ScenarioDefinition:
        path = self._path(scenario_id)
        if not path.exists():
            raise ScenarioNotFoundError(f"scenario {scenario_id!r} not found")
        path.write_text(scenario.model_dump_json(indent=2))
        return scenario

    def delete(self, scenario_id: str) -> bool:
        path = self._path(scenario_id)
        if not path.exists():
            return False
        path.unlink()
        return True
