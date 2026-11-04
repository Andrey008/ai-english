import asyncio
import time

from app.ws_session import PLAYBACK_TAIL_MARGIN_S, PCM_BYTES_PER_SECOND, PlaybackClock


def test_waits_for_audio_duration_plus_margin():
    clock = PlaybackClock()
    clock.add(PCM_BYTES_PER_SECOND // 5)  # 0.2s
    clock.add(PCM_BYTES_PER_SECOND // 5)  # back-to-back: 0.4s total
    started = time.monotonic()
    asyncio.run(clock.wait_drained())
    elapsed = time.monotonic() - started
    assert 0.4 + PLAYBACK_TAIL_MARGIN_S - 0.05 <= elapsed < 0.4 + PLAYBACK_TAIL_MARGIN_S + 0.2


def test_empty_clock_returns_immediately():
    started = time.monotonic()
    asyncio.run(PlaybackClock().wait_drained())
    assert time.monotonic() - started < 0.05
