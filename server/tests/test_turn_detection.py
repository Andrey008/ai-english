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
