"""Character/preset manager (STORY-02-07): CRUD over JSON presets on
disk, per `ARCHITECTURE.md` §3.1's schema. Validation is Pydantic's job
— invalid `tts_engine`/`correction_style` values, missing required
fields, etc. fail at the FastAPI request-parsing layer, before any
write happens (fail fast at write time, not mid-session).

`role_description` (not a raw `system_prompt`) is the per-character
customization point (`STORY-03-02`, `ADR-0008`) — the WS pipeline
composes the actual system prompt at session-start via
`persona.render_system_prompt`, so every character gets the validated
proactive-behavior contract by construction. `system_prompt_override`
is an escape hatch for bypassing the builder entirely; expected unused
in practice.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.config import resolve_repo_path
from app.persona import DEFAULT_ROLE_DESCRIPTION

DEFAULT_CHARACTER_ID = "alex_default"


class CharacterPreset(BaseModel):
    id: str
    name: str
    gender: Literal["male", "female"]
    accent: str = "en_US"
    avatar_path: str = ""
    role_description: str
    system_prompt_override: str | None = None
    tts_voice_id: str
    tts_engine: Literal["piper", "kokoro", "xtts"] = "piper"
    voice_reference_path: str | None = None
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    correction_style: Literal["off", "end_of_session", "live_gentle"] = "off"
    memory_enabled: bool = True
    # EPIC-10 / ADR-0016 §6: "interview" runs the prep-base interview
    # (app/interview/); every other character stays "conversation".
    session_mode: Literal["conversation", "interview"] = "conversation"


class PresetError(RuntimeError):
    pass


class PresetExistsError(PresetError):
    pass


class PresetNotFoundError(PresetError):
    pass


class PresetStore:
    def __init__(self, config: dict[str, Any]):
        self._dir: Path = resolve_repo_path(config["presets"]["dir"])
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, character_id: str) -> Path:
        return self._dir / f"{character_id}.json"

    def create(self, preset: CharacterPreset) -> CharacterPreset:
        path = self._path(preset.id)
        if path.exists():
            raise PresetExistsError(f"character {preset.id!r} already exists")
        path.write_text(preset.model_dump_json(indent=2))
        return preset

    def get(self, character_id: str) -> CharacterPreset | None:
        path = self._path(character_id)
        if not path.exists():
            return None
        return CharacterPreset.model_validate_json(path.read_text())

    def list(self) -> list[CharacterPreset]:
        return [
            CharacterPreset.model_validate_json(p.read_text())
            for p in sorted(self._dir.glob("*.json"))
        ]

    def update(self, character_id: str, preset: CharacterPreset) -> CharacterPreset:
        path = self._path(character_id)
        if not path.exists():
            raise PresetNotFoundError(f"character {character_id!r} not found")
        path.write_text(preset.model_dump_json(indent=2))
        return preset

    def delete(self, character_id: str) -> bool:
        path = self._path(character_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def ensure_seed(self) -> None:
        """At least one usable preset out of the box."""
        if self.get(DEFAULT_CHARACTER_ID) is not None:
            return
        self.create(
            CharacterPreset(
                id=DEFAULT_CHARACTER_ID,
                name="Alex",
                gender="female",
                accent="en_US",
                role_description=DEFAULT_ROLE_DESCRIPTION,
                tts_voice_id="af_jessica",
                tts_engine="kokoro",
                correction_style="off",
            )
        )
