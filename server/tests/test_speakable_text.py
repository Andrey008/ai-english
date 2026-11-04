from app.tts_service import speakable_text


def test_strips_emoji_and_joiners():
    assert speakable_text("I'm dying to hear one! 😜") == "I'm dying to hear one!"
    assert speakable_text("Family 👨‍👩‍👧 time ❤️") == "Family time"


def test_emoji_only_sentence_becomes_empty():
    assert speakable_text("😂🍿") == ""


def test_strips_markdown_emphasis():
    assert speakable_text("**Great** idea, _really_.") == "Great idea, really."


def test_drops_bracketed_placeholders():
    assert (
        speakable_text("Do you think they'll beat [insert opponent]?")
        == "Do you think they'll beat?"
    )
    assert speakable_text("[laughs]") == ""


def test_plain_text_untouched():
    assert speakable_text("Hello there, how are you?") == "Hello there, how are you?"
