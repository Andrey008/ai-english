"""Engine selection and the Kokoro chunking (ADR-0018). No model files needed."""
from __future__ import annotations

import asyncio

import numpy as np

from app.tts_service import OUTPUT_SAMPLE_RATE, KokoroEngine, TTSService, Voice


class FakeKokoro:
    def __init__(self, seconds: float = 1.0):
        self.seconds = seconds
        self.calls: list[tuple[str, str, str]] = []

    def create(self, text, voice, speed, lang):
        self.calls.append((text, voice, lang))
        return np.full(int(24000 * self.seconds), 0.5, dtype=np.float32), 24000


def make_service(kokoro_ready: bool = True) -> TTSService:
    service = TTSService({"tts": {
        "voice": "en_US-lessac-medium", "voices_dir": "poc/voices",
        "kokoro": {"model_path": "models/kokoro/x.onnx", "voices_path": "models/kokoro/x.bin"},
    }})
    service._kokoro._kokoro = FakeKokoro()
    service._kokoro._voices = frozenset({"af_heart", "bm_george"})
    service._kokoro_ready = kokoro_ready
    return service


def test_resolve_picks_kokoro_when_the_voice_exists():
    assert make_service().resolve("kokoro", "af_heart") == Voice("kokoro", "af_heart")


def test_resolve_falls_back_to_default_piper_voice():
    service = make_service()
    assert service.resolve("kokoro", "af_nobody") == Voice("piper", "en_US-lessac-medium")
    assert make_service(kokoro_ready=False).resolve("kokoro", "af_heart") == Voice("piper", "en_US-lessac-medium")
    assert service.resolve("piper", "en_GB-alan-medium") == Voice("piper", "en_GB-alan-medium")
    assert service.resolve("xtts", None) == Voice("piper", "en_US-lessac-medium")


def test_kokoro_stream_is_16khz_pcm_in_short_chunks_with_accent_lang():
    async def run():
        service = make_service()
        return service, [c async for c in service.synthesize_stream("Hi.", Voice("kokoro", "bm_george"))]

    service, chunks = asyncio.run(run())
    assert sum(len(c) for c in chunks) == OUTPUT_SAMPLE_RATE * 2  # 1s of int16 mono
    assert len(chunks) == 4 and all(len(c) <= OUTPUT_SAMPLE_RATE // 2 for c in chunks)
    assert service._kokoro._kokoro.calls == [("Hi.", "bm_george", "en-gb")]


def test_kokoro_engine_unavailable_without_model_files():
    engine = KokoroEngine({"model_path": "models/kokoro/missing.onnx", "voices_path": "models/kokoro/missing.bin"})
    assert engine.available is False
