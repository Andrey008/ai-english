import pytest

from app.persona import DEFAULT_SYSTEM_PROMPT, ENGLISH_LEVELS
from app.presets import CharacterPreset
from app.scenarios import ScenarioDefinition
from app.ws_session import compose_system_prompt

PRESET = CharacterPreset(
    id="t", name="Tess", gender="female", role_description="A test persona.", tts_voice_id="v"
)


def test_default_persona_gets_level_block():
    prompt = compose_system_prompt(None, None, "B1", None)
    assert prompt.startswith(DEFAULT_SYSTEM_PROMPT)
    assert "USER'S ENGLISH LEVEL: intermediate (B1)" in prompt
    assert "PAST CONVERSATIONS" not in prompt


@pytest.mark.parametrize("level", sorted(ENGLISH_LEVELS))
def test_every_level_renders(level):
    assert ENGLISH_LEVELS[level][0] in compose_system_prompt(PRESET, None, level, None)


def test_memory_is_framed_as_past_and_comes_last():
    prompt = compose_system_prompt(PRESET, None, "C1", "Pat plans to watch the game this weekend.")
    assert prompt.startswith("You are Tess. A test persona.")
    level_at = prompt.index("USER'S ENGLISH LEVEL")
    memory_at = prompt.index("BACKGROUND FROM PAST CONVERSATIONS")
    assert level_at < memory_at
    assert "This is a NEW conversation" in prompt
    assert "Pat plans to watch" in prompt


def test_scenario_sits_between_persona_and_level():
    scenario = ScenarioDefinition(
        id="s", title="Coffee", difficulty=1, character_role_prompt_addendum="You are a barista.",
        goal="Order a coffee.", opening_line_hint="Hi!",
    )
    prompt = compose_system_prompt(PRESET, scenario, "A2", None)
    assert prompt.index("You are Tess") < prompt.index("SCENARIO: Coffee") < prompt.index("USER'S ENGLISH LEVEL")


def test_override_replaces_persona_but_keeps_level():
    preset = PRESET.model_copy(update={"system_prompt_override": "RAW PROMPT"})
    prompt = compose_system_prompt(preset, None, "native", None)
    assert prompt.startswith("RAW PROMPT\n\nUSER'S ENGLISH LEVEL: native-like")
