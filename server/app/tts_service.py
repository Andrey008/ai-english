"""Persistent TTS service (STORY-02-03).

Unlike STT, `piper-tts` ships no persistent server binary — ADR-0006
flagged Piper as needing "similar wrapping" to STT, custom. Rather than
shell out to the `piper` CLI (PoC's approach, one model load per call)
or stand up Piper's own `http_server` module (needs Flask, redundant
with the FastAPI process we already have), this loads voices in-process
via `piper.voice.PiperVoice` and keeps them warm for the server's
lifetime — no subprocess, no model reload per call.

Kokoro (ADR-0018) is the second engine: much more natural voices, all
in one ~330MB ONNX model + one voices file, CPU-only (it doesn't compete
with Ollama for the GPU). ~0.4s per sentence vs Piper's ~0.06s. A
character picks its engine with `tts_engine`; Piper stays the fallback.
"""
from __future__ import annotations

import asyncio
import logging
import re
import threading
import unicodedata
from dataclasses import dataclass
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


@dataclass(frozen=True)
class Voice:
    engine: str  # "piper" | "kokoro"
    voice_id: str


# Kokoro voice ids are `<accent><gender>_<name>`: a = American, b = British.
def _kokoro_lang(voice_id: str) -> str:
    return "en-gb" if voice_id.startswith("b") else "en-us"


# Send a sentence in pieces of about this long, like Piper's chunks, so
# the client starts playing and the playback clock advances smoothly.
KOKORO_CHUNK_S = 0.25


class KokoroEngine:
    def __init__(self, config: dict[str, Any]):
        self._model_path = resolve_repo_path(config["model_path"])
        self._voices_path = resolve_repo_path(config["voices_path"])
        self._speed = float(config.get("speed", 1.0))
        self._kokoro = None
        self._voices: frozenset[str] = frozenset()
        # One synthesis at a time: parallel ONNX runs only fight over the
        # same CPU cores and make every sentence slower.
        self._run_lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self._model_path.exists() and self._voices_path.exists()

    def load(self) -> None:
        from kokoro_onnx import Kokoro

        self._kokoro = Kokoro(str(self._model_path), str(self._voices_path))
        self._voices = frozenset(self._kokoro.get_voices())
        self._synth("Hello.", "af_heart")  # the first run is several times slower

    def has_voice(self, voice_id: str) -> bool:
        return voice_id in self._voices

    def _synth(self, text: str, voice_id: str) -> tuple[np.ndarray, int]:
        with self._run_lock:
            return self._kokoro.create(text, voice=voice_id, speed=self._speed, lang=_kokoro_lang(voice_id))

    def synthesize(self, text: str, voice_id: str):
        """Yields 16-bit PCM at OUTPUT_SAMPLE_RATE (blocking; run in a thread)."""
        audio, sample_rate = self._synth(text, voice_id)
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        pcm = _to_output_rate(pcm, sample_rate)
        step = int(OUTPUT_SAMPLE_RATE * KOKORO_CHUNK_S) * 2
        for i in range(0, len(pcm), step):
            yield pcm[i:i + step]


class TTSService:
    def __init__(self, config: dict[str, Any]):
        tts_config = config["tts"]
        self._voices_dir = resolve_repo_path(tts_config["voices_dir"])
        self._default_voice_id = tts_config["voice"]
        self._voices: dict[str, PiperVoice] = {}
        self._lock = asyncio.Lock()
        kokoro_config = tts_config.get("kokoro")
        self._kokoro = KokoroEngine(kokoro_config) if kokoro_config else None
        self._kokoro_ready = False

    async def start(self) -> None:
        logger.info("tts_service_starting", extra={"default_voice": self._default_voice_id})
        await self._get_voice(self._default_voice_id)
        if self._kokoro is not None:
            if self._kokoro.available:
                await asyncio.to_thread(self._kokoro.load)
                self._kokoro_ready = True
            else:
                logger.warning("tts_kokoro_model_missing", extra={"fallback": self._default_voice_id})
        logger.info("tts_service_ready", extra={"loaded_voices": list(self._voices), "kokoro": self._kokoro_ready})

    def resolve(self, engine: str | None, voice_id: str | None) -> Voice:
        """The voice a character asked for, or the default Piper voice if
        that engine/voice isn't available here (never fail a session over it)."""
        if engine == "kokoro" and voice_id:
            if self._kokoro_ready and self._kokoro.has_voice(voice_id):
                return Voice("kokoro", voice_id)
            logger.warning("tts_voice_unavailable", extra={"engine": engine, "voice_id": voice_id})
            return Voice("piper", self._default_voice_id)
        return Voice("piper", voice_id or self._default_voice_id)

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
        self, text: str, voice: Voice | str | None = None
    ) -> AsyncIterator[bytes]:
        """Stream 16-bit PCM/16kHz audio chunks for `text` from an already-warm
        voice. A plain string is a Piper voice id."""
        if not isinstance(voice, Voice):
            voice = Voice("piper", voice or self._default_voice_id)
        if voice.engine == "kokoro":
            chunks = lambda: self._kokoro.synthesize(text, voice.voice_id)  # noqa: E731
        else:
            piper_voice = await self._get_voice(voice.voice_id)
            chunks = lambda: (  # noqa: E731
                _to_output_rate(c.audio_int16_bytes, c.sample_rate) for c in piper_voice.synthesize(text)
            )
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def worker() -> None:
            try:
                for pcm in chunks():
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
                raise TTSServiceError(f"{voice.engine} synthesis failed: {item}") from item
            yield item
