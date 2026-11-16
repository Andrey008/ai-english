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

`--reload` and the default host bind to loopback only. For a phone on the
LAN or Tailscale add `--host 0.0.0.0`. Behind a tunnel or reverse proxy,
keep `--host 127.0.0.1` and point the tunnel at `http://127.0.0.1:8000`.

## Auth (ADR-0017)

Every route except `/healthz` needs `Authorization: Bearer <token>`, on
HTTP and on the `/ws/session` upgrade. Each device gets its own token:

```
uv run python scripts/devices.py create "Pixel"   # prints the token once
uv run python scripts/devices.py list
uv run python scripts/devices.py revoke <device id>
```

Paste the token into the app (Settings → Server connection). Revoking
works while the server runs. The live scripts in `scripts/` read
`AI_ENGLISH_TOKEN`, from the environment or from `server/.env`.

```
curl -H "Authorization: Bearer $AI_ENGLISH_TOKEN" http://127.0.0.1:8000/auth/me
```

`AI_ENGLISH__SECURITY__AUTH_REQUIRED=false` turns auth off for a throwaway
local run. `/docs` is off unless `AI_ENGLISH__SECURITY__API_DOCS=true` is set.

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
