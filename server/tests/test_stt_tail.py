import asyncio

from app.stt_service import STTService


class FakeWhisper:
    """Plain pass returns `plain`; the timestamped recheck returns `stamped`."""

    def __init__(self, plain: str, stamped: str):
        self.plain, self.stamped, self.calls = plain, stamped, []

    async def post(self, path, files, data):
        self.calls.append(data)
        text = self.stamped if data.get("no_timestamps") == "false" else self.plain

        class Resp:
            status_code = 200

        resp = Resp()
        resp.text = text
        return resp


def service(fake) -> STTService:
    stt = STTService({"stt": {"whisper_server_bin": "x", "model_path": "y", "host": "h", "port": 1}})
    stt._client = fake
    return stt


def test_invented_closing_thank_you_is_trimmed():
    fake = FakeWhisper(" It works now, you know.\n Thank you.\n", " It works now, you know.\n")
    assert asyncio.run(service(fake).transcribe(b"wav")) == "It works now, you know."
    assert len(fake.calls) == 2


def test_spoken_thank_you_survives_the_recheck():
    fake = FakeWhisper(" That helps a lot. Thank you.", " That helps a lot. Thank you.")
    assert asyncio.run(service(fake).transcribe(b"wav")) == "That helps a lot. Thank you."


def test_normal_reply_needs_no_recheck():
    fake = FakeWhisper(" I like snow in the evening.", "unused")
    assert asyncio.run(service(fake).transcribe(b"wav")) == "I like snow in the evening."
    assert len(fake.calls) == 1
