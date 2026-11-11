import pytest

from app.turn_detection import looks_incomplete


@pytest.mark.parametrize(
    "text",
    [
        "I went to the shop and",
        "Because, um",
        "I think that...",
        "My favourite food is, like —",
        "I was going to the",
        "We stayed there for,",
        "Yesterday I",
        "It was really",
    ],
)
def test_unfinished_endings_are_held(text):
    assert looks_incomplete(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "I went to the shop.",
        "Do you like it?",
        "That's so cool!",
        "I don't know",
        "What about you",
        "I like it too",
        "Not much to talk about",
        "Are you going to?",
    ],
)
def test_finished_endings_are_not_held(text):
    assert not looks_incomplete(text)


def test_turn_patience_by_level():
    from app.config import get_config
    from app.ws_session import turn_patience_s

    config = get_config()
    waits = [turn_patience_s(config, level) for level in ("A2", "B1", "B2", "C1", "native")]
    assert waits == sorted(waits, reverse=True) and waits[-1] == 0.0  # lower level -> longer wait
    assert turn_patience_s({"vad": {}}, "B1") == 0.0  # not configured -> old behaviour


def test_short_noise_hallucinations_are_dropped():
    from app.ws_session import NON_SPEECH_MARKER, PCM_BYTES_PER_SECOND, is_noise_hallucination

    short, long = int(1.6 * PCM_BYTES_PER_SECOND), 5 * PCM_BYTES_PER_SECOND
    assert is_noise_hallucination("Thank you.", short)
    assert is_noise_hallucination(NON_SPEECH_MARKER.sub("", "*clicks*").strip(), short)
    assert not is_noise_hallucination("Thank you.", long)  # long enough to be real speech
    assert not is_noise_hallucination("I like snow.", short)
