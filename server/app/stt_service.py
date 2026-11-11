"""Persistent STT service (STORY-02-02).

Wraps whisper.cpp's `whisper-server` as a subprocess managed by this
app's own lifecycle: started once on server boot (model loaded once,
kept warm), stopped on shutdown. Callers get a `transcribe()` call that
hits the already-warm model over HTTP — no per-call process spawn or
model reload.

Architecture choice (whisper-server HTTP vs. a custom incremental
wrapper around whisper-stream) is recorded in ADR-0007 — short version:
measured warm whisper-server latency (~420ms) already beats the PoC's
own streaming number, so the simpler, officially-supported option won.
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from app.config import resolve_repo_path

logger = logging.getLogger("ai_english.stt")


# Whisper's prompt window is 224 tokens; the end of the reply (where its
# question usually is) is the useful part.
PROMPT_MAX_CHARS = 600


class STTServiceError(RuntimeError):
    pass


class STTService:
    def __init__(self, config: dict[str, Any]):
        stt_config = config["stt"]
        self._bin = resolve_repo_path(stt_config["whisper_server_bin"])
        self._model_path = resolve_repo_path(stt_config["model_path"])
        self._host = stt_config["host"]
        self._port = int(stt_config["port"])
        self._startup_timeout_s = float(stt_config.get("startup_timeout_s", 60))
        # Pinned, never "auto": large-v3-turbo is multilingual, and accented
        # English must not be detected as another language.
        self._language = stt_config.get("language", "en")
        self._base_url = f"http://{self._host}:{self._port}"
        self._process: subprocess.Popen | None = None
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        if not self._bin.exists():
            raise STTServiceError(f"whisper-server binary not found: {self._bin}")
        if not self._model_path.exists():
            raise STTServiceError(f"STT model not found: {self._model_path}")

        logger.info("stt_service_starting", extra={"bin": str(self._bin), "model": str(self._model_path)})
        self._process = subprocess.Popen(
            [
                str(self._bin),
                "-m", str(self._model_path),
                "--host", self._host,
                "--port", str(self._port),
                "-l", self._language,
                "-nt",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=30.0)
        await self._wait_until_ready()
        logger.info("stt_service_ready", extra={"base_url": self._base_url})

    async def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + self._startup_timeout_s
        assert self._process is not None and self._client is not None
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise STTServiceError(
                    f"whisper-server exited early (code {self._process.returncode})"
                )
            try:
                resp = await self._client.get("/")
                if resp.status_code < 500:
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.5)
        raise STTServiceError("whisper-server did not become ready in time")

    async def transcribe(self, wav_bytes: bytes, prompt: str | None = None) -> str:
        """Transcribe a 16kHz mono WAV clip. `prompt` is whisper's initial
        prompt: text that came just before this clip (the character's
        last reply), which biases decoding towards the words in play.
        Raises STTServiceError on failure."""
        if self._client is None:
            raise STTServiceError("STT service not started")
        data = {"temperature": "0.0", "response_format": "text"}
        if prompt:
            data["prompt"] = prompt[-PROMPT_MAX_CHARS:]
        try:
            resp = await self._client.post(
                "/inference",
                files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                data=data,
            )
        except httpx.TransportError as exc:
            raise STTServiceError(f"whisper-server request failed: {exc}") from exc
        if resp.status_code != 200:
            raise STTServiceError(f"whisper-server returned {resp.status_code}: {resp.text}")
        return resp.text.strip()

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None
        logger.info("stt_service_stopped")
