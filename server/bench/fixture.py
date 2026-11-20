"""Benchmark conversations: scripts (committed) and recorded fixtures.

A *script* (`bench/scripts/*.yaml`) is a fixed conversation: the user's
lines plus a reference reply for each. A *fixture* (`bench/fixtures/
<name>/fixture.json`, gitignored — it holds the developer's voice) is a
script after recording: each turn also gets the WAV the user read it
into and, once `transcribe.py` has run, whisper's transcript of it.

Every backend is fed the same fixture, so prompts are identical down to
the byte (see `run.py` on teacher-forced history).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

BENCH_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = BENCH_DIR / "scripts"
FIXTURES_DIR = BENCH_DIR / "fixtures"


@dataclass
class Turn:
    user_script: str
    assistant_reference: str
    audio: str | None = None  # WAV file name, relative to the fixture dir
    user_stt: str | None = None

    def user_text(self, source: str) -> str:
        """`stt` = what the real pipeline would hand the LLM; `script` =
        the line as written (no recording needed)."""
        if source == "stt":
            if self.user_stt is None:
                raise ValueError("turn has no STT transcript — run bench/transcribe.py first")
            return self.user_stt
        return self.user_script


@dataclass
class Fixture:
    name: str
    character_id: str
    english_level: str
    turns: list[Turn] = field(default_factory=list)
    dir: Path | None = None

    @classmethod
    def from_script(cls, path: Path) -> Fixture:
        data = yaml.safe_load(path.read_text())
        return cls(
            name=data["name"],
            character_id=data["character_id"],
            english_level=data["english_level"],
            turns=[Turn(user_script=t["user"], assistant_reference=t["assistant"]) for t in data["turns"]],
        )

    @classmethod
    def load(cls, path: Path) -> Fixture:
        """`path` is a fixture dir, its `fixture.json`, or a script YAML."""
        if path.suffix in (".yaml", ".yml"):
            return cls.from_script(path)
        if path.is_dir():
            path = path / "fixture.json"
        data = json.loads(path.read_text())
        turns = [Turn(**t) for t in data.pop("turns")]
        return cls(**data, turns=turns, dir=path.parent)

    def save(self, fixture_dir: Path) -> Path:
        fixture_dir.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data.pop("dir")
        path = fixture_dir / "fixture.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        self.dir = fixture_dir
        return path
