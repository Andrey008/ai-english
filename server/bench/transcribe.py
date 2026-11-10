"""Transcribe a recorded fixture with the production STT (whisper-server).

    uv run python -m bench.transcribe bench/fixtures/smalltalk_b1

Same binary, model and cleanup as the live pipeline (`STTService`,
`NON_SPEECH_MARKER`), so the LLM benchmark gets the text a real session
would have handed the model — including whisper's mistakes. Run once;
every backend then reuses the same transcripts.
Starts its own whisper-server on the configured port: don't run it while
the main server is up.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

from app.config import get_config  # noqa: E402
from app.stt_service import STTService  # noqa: E402
from app.ws_session import NON_SPEECH_MARKER  # noqa: E402
from bench.fixture import Fixture  # noqa: E402


async def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fixture", type=Path, help="recorded fixture dir")
    ap.add_argument("--force", action="store_true", help="re-transcribe turns that already have a transcript")
    args = ap.parse_args(argv)

    fixture = Fixture.load(args.fixture)
    pending = {i for i, t in enumerate(fixture.turns) if t.audio and (args.force or t.user_stt is None)}
    if not pending:
        print("nothing to transcribe")
        return

    stt = STTService(get_config())
    await stt.start()
    try:
        for index, turn in enumerate(fixture.turns, start=1):
            if index - 1 not in pending:
                continue
            started = time.perf_counter()
            text = await stt.transcribe((fixture.dir / turn.audio).read_bytes())
            turn.user_stt = NON_SPEECH_MARKER.sub("", text).strip()
            fixture.save(fixture.dir)
            same = "" if _norm(turn.user_stt) == _norm(turn.user_script) else "   ≠ script"
            print(f"[{index:>2}] {time.perf_counter() - started:4.2f}s  {turn.user_stt}{same}")
    finally:
        await stt.stop()
    print(f"saved {fixture.dir / 'fixture.json'}")


def _norm(text: str) -> str:
    return " ".join("".join(c for c in text.lower() if c.isalnum() or c.isspace()).split())


if __name__ == "__main__":
    asyncio.run(main())
