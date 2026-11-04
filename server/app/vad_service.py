"""Turn-boundary detection: Silero VAD, streaming (STORY-02-05).

Ported from the PoC's `VADIterator` usage (`bargein_spike.py`). Feed raw
16kHz mono PCM16 bytes as they arrive off the WS connection; get back
`speech_start`/`speech_end` events, the latter carrying the full
utterance's PCM bytes ready for STT. This is what determines turn
boundaries — whisper.cpp's own internal VAD-slicing is *not* used
(see ADR-0007's rationale for why STT gets called batch-per-utterance).
"""
from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np
import torch
from silero_vad import VADIterator, load_silero_vad

CHUNK_SAMPLES = 512  # ~32ms at 16kHz, Silero's expected frame size
SAMPLE_WIDTH_BYTES = 2  # 16-bit PCM
# Silero only fires "start" a few frames into speech; without some audio
# from before that point the utterance's first word gets clipped
# (STORY-05-11: "of what we were talking about" lost its opening words).
PRE_ROLL_CHUNKS = 10  # ~320ms


class TurnSegmenter:
    def __init__(self, config: dict[str, Any]):
        vad_config = config["vad"]
        self._sample_rate = 16000
        model = load_silero_vad()
        self._vad_iter = VADIterator(
            model,
            sampling_rate=self._sample_rate,
            threshold=0.5,
            min_silence_duration_ms=vad_config.get("silence_cutoff_ms", 600),
        )
        self._buffer = bytearray()
        self._utterance = bytearray()
        self._in_speech = False
        self._pre_roll: deque[bytes] = deque(maxlen=PRE_ROLL_CHUNKS)

    def reset(self) -> None:
        self._vad_iter.reset_states()
        self._buffer.clear()
        self._utterance.clear()
        self._in_speech = False
        self._pre_roll.clear()

    def feed(self, pcm16_bytes: bytes) -> list[dict]:
        events: list[dict] = []
        self._buffer.extend(pcm16_bytes)
        chunk_bytes = CHUNK_SAMPLES * SAMPLE_WIDTH_BYTES
        while len(self._buffer) >= chunk_bytes:
            chunk = bytes(self._buffer[:chunk_bytes])
            del self._buffer[:chunk_bytes]

            arr = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
            result = self._vad_iter(torch.from_numpy(arr))

            if result and "start" in result and not self._in_speech:
                self._in_speech = True
                self._utterance = bytearray(b"".join(self._pre_roll))
                self._pre_roll.clear()
                events.append({"type": "speech_start"})

            if self._in_speech:
                self._utterance.extend(chunk)
            else:
                self._pre_roll.append(chunk)

            if result and "end" in result and self._in_speech:
                self._in_speech = False
                events.append({"type": "speech_end", "audio": bytes(self._utterance)})
                self._utterance = bytearray()

        return events
