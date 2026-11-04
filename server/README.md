# AI English Voice Companion — Server

FastAPI backend (Phase 2, `EPIC-02`). See `Docs/stories/epic-02/` in the
repo's gitignored `Docs/` tree for the story-by-story build plan — this
README only covers running what exists.

## Setup

```
cd server
uv sync
```

External pieces, not in git (paths are relative to the repo root and
set in `models_config/default.yaml`):

- **Ollama** with the conversational model: `ollama pull gemma2:27b`.
- **whisper.cpp** built at `poc/whisper.cpp/` (`whisper-server` binary +
  `models/ggml-medium.en.bin`) — see `poc/results/setup.md`.
- **Piper voices** in `poc/voices/`: the `.onnx.json` configs are
  committed, the `.onnx` models (~60MB each) are not — download the
  matching `en_US-lessac-medium`, `en_US-amy-medium`, `en_GB-alan-medium`
  models from the `rhasspy/piper-voices` release on Hugging Face.

## Run

```
uv run uvicorn app.main:app --reload
```

Then `curl http://127.0.0.1:8000/healthz` → `{"status": "ok"}`.

## Config

Defaults live in `models_config/default.yaml` (reflects
`poc/results/FINDINGS.md`'s Phase 1 component choices — STT/LLM/TTS
model and engine selection). Override:

- A single value: env var `AI_ENGLISH__<SECTION>__<KEY>`, e.g.
  `AI_ENGLISH__LLM__MODEL=qwen2.5:32b uv run uvicorn app.main:app`
- The whole file: `AI_ENGLISH_CONFIG_FILE=/path/to/other.yaml`

## Tests

```
uv run pytest
```

Unit tests only (no Ollama/whisper needed). End-to-end checks against a
running server live in `scripts/` (e.g. `live_persona_spotcheck.py`).

## Status

Full pipeline: WebSocket `/ws/session` (Silero VAD → whisper.cpp STT →
Ollama LLM → Piper TTS, protocol documented in `app/ws_session.py`),
REST `/characters` and `/scenarios`, SQLite persistence, character
memory, in-session context compaction, text-based end-of-turn detection.
