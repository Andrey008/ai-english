"""Persistent TTS service (STORY-02-03).

Unlike STT, `piper-tts` ships no persistent server binary — ADR-0006
flagged Piper as needing "similar wrapping" to STT, custom. Rather than
shell out to the `piper` CLI (PoC's approach, one model load per call)
or stand up Piper's own `http_server` module (needs Flask, redundant
with the FastAPI process we already have), this loads voices in-process
via `piper.voice.PiperVoice` and keeps them warm for the server's
lifetime — no subprocess, no model reload per call.
"""
from __future__ import annotations

import asyncio
import logging
import re
import threading
import unicodedata
from typing import Any, AsyncIterator

import numpy as np
import torch
import torchaudio.functional as F
from piper.voice import PiperVoice

from app.config import resolve_repo_path

logger = logging.getLogger("ai_english.tts")

_SENTINEL = object()

# The WS protocol's fixed playback rate (`ws_session.py`); Piper voices
# synthesize at their own native rate (e.g. 22050Hz for `*-medium`), so
# every chunk is resampled to this before it leaves the service.
OUTPUT_SAMPLE_RATE = 16000


_MARKDOWN = re.compile(r"[*_#`~]+")
# Square brackets in a reply are never speech: template placeholders
# gemma2 occasionally leaves in ("[insert opponent]") or stage notes.
_BRACKETED = re.compile(r"\[[^\]]*\]")
_SPACES = re.compile(r"\s{2,}")


def speakable_text(text: str) -> str:
    """Strip what TTS shouldn't read aloud: emoji/pictographs (LLMs like
    gemma2 sprinkle them in — Piper tried to voice them, STORY-05-11),
    [bracketed] placeholders and markdown emphasis characters. Empty
    result = nothing to say."""
    kept = "".join(
        c for c in text
        if unicodedata.category(c) not in ("So", "Sk", "Cs", "Co") and c not in "\u200d\ufe0f\ufe0e"
    )
    kept = _MARKDOWN.sub("", _BRACKETED.sub("", kept))
    return _SPACES.sub(" ", kept).replace(" ?", "?").strip()


def _to_output_rate(pcm16: bytes, sample_rate: int) -> bytes:
    if sample_rate == OUTPUT_SAMPLE_RATE:
        return pcm16
    x = torch.from_numpy(np.frombuffer(pcm16, dtype=np.int16).astype(np.float32))
    y = F.resample(x, sample_rate, OUTPUT_SAMPLE_RATE)
    return y.round().clamp(-32768, 32767).to(torch.int16).numpy().tobytes()


class TTSServiceError(RuntimeError):
    pass


class TTSService:
    def __init__(self, config: dict[str, Any]):
        tts_config = config["tts"]
        self._voices_dir = resolve_repo_path(tts_config["voices_dir"])
        self._default_voice_id = tts_config["voice"]
        self._voices: dict[str, PiperVoice] = {}
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        logger.info("tts_service_starting", extra={"default_voice": self._default_voice_id})
        await self._get_voice(self._default_voice_id)
        logger.info("tts_service_ready", extra={"loaded_voices": list(self._voices)})

    async def stop(self) -> None:
        self._voices.clear()
        logger.info("tts_service_stopped")

    async def _get_voice(self, voice_id: str) -> PiperVoice:
        if voice_id in self._voices:
            return self._voices[voice_id]
        async with self._lock:
            if voice_id in self._voices:
                return self._voices[voice_id]
            model_path = self._voices_dir / f"{voice_id}.onnx"
            config_path = self._voices_dir / f"{voice_id}.onnx.json"
            if not model_path.exists():
                raise TTSServiceError(f"Piper voice model not found: {model_path}")
            logger.info("tts_voice_loading", extra={"voice_id": voice_id})
            voice = await asyncio.to_thread(PiperVoice.load, str(model_path), str(config_path))
            self._voices[voice_id] = voice
            logger.info("tts_voice_loaded", extra={"voice_id": voice_id})
            return voice

    async def synthesize_stream(
        self, text: str, voice_id: str | None = None
    ) -> AsyncIterator[bytes]:
        """Stream 16-bit PCM/16kHz audio chunks for `text` from an already-warm voice."""
        voice = await self._get_voice(voice_id or self._default_voice_id)
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def worker() -> None:
            try:
                for chunk in voice.synthesize(text):
                    pcm = _to_output_rate(chunk.audio_int16_bytes, chunk.sample_rate)
                    loop.call_soon_threadsafe(queue.put_nowait, pcm)
            except Exception as exc:  # noqa: BLE001 — surfaced to the async caller below
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

        threading.Thread(target=worker, daemon=True).start()

        while True:
            item = await queue.get()
            if item is _SENTINEL:
                return
            if isinstance(item, Exception):
                raise TTSServiceError(f"Piper synthesis failed: {item}") from item
            yield item
