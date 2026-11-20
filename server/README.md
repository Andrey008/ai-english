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
- **Kokoro model** in `models/kokoro/` (gitignored, ADR-0018): the characters' voices. Without it they fall back to Piper.
  ```
  mkdir -p models/kokoro && cd models/kokoro
  base=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0
  curl -LO $base/kokoro-v1.0.onnx && curl -LO $base/voices-v1.0.bin
  ```

## Run

```
uv run uvicorn app.main:app --reload
```

Then `curl http://127.0.0.1:8000/healthz` → `{"status": "ok"}`.

`--reload` and the default host bind to loopback only. For a phone on the
LAN or Tailscale add `--host 0.0.0.0`. Behind a tunnel or reverse proxy,
keep `--host 127.0.0.1` and point the tunnel at `http://127.0.0.1:8000`.

### Menu-bar app (macOS)

`uv run python scripts/menubar.py` puts a status dot in the menu bar. It shows these states:

- ⚪ stopped;
- 🟡 starting or loading the model;
- 🟢 ready;
- 🔴 exited.

From the menu you can:

- Start, Stop or Restart the server. It runs under `caffeinate -i`, and the log goes to `server/logs/server.log`.
- See what Ollama has loaded.
- Unload every other Ollama model. This happens before each start by default.
- See which processes use more than 1 GB of memory.

`scripts/install_menubar.sh` makes it start at login (LaunchAgent).

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

## Practice stats

`GET /stats?days=30&tz=Europe/Kyiv` (both optional; `tz` defaults to the
server's local zone) returns how much you practiced: totals, today,
last 7 / 30 days, the day streak, a per-day series, and breakdowns by
character and by kind (free / scenario / interview). Computed in
`app/stats.py` from the `turns` table:

- `speaking_s` / `listening_s` — your utterance audio and the character's
  TTS audio (`turns.audio_ms`). Turns from before that column existed
  are estimated from the word count; `estimated_audio_s` says how much.
- `practice_s` — active conversation time: the time between turns, with
  silence beyond the speech capped at `stats.idle_cap_s` (default 90s)
  per gap, so an idle app or a conversation resumed days later doesn't
  inflate it.
- `words_per_minute` — only from measured audio, once there is ≥ 1 min
  of it. VAD padding and pauses are included, so it reads a bit low.

## Vocabulary (AE-5)

Words you didn't understand in a conversation, collected for learning in
EnglishDom (added there by hand — no SRS here). `app/vocabulary.py`
runs after a conversation ends, off the live path, and reads only the
turns since `sessions.vocab_scanned_until`, so a resumed conversation's
old history isn't analysed again (plus the last character line before
it, in case you ask about it first thing). Two triggers, each its own
small local-LLM prompt, skipped when there is nothing to look at:

- **a re-ask** — "what does X mean?", "sorry, X?", "I didn't get this
  word": the word is taken from the character's line (exact spelling;
  your line is STT). It must be tied to that question — the question
  names it (fuzzy, for STT typos) or names no word at all.
- **a bookmark** — the WS `bookmark` frame ("Unknown word" button):
  anchored to the character line playing or just played; up to
  `vocabulary.max_words_per_bookmark` hard words are picked from it.

API: `GET /vocabulary?status=new|added|dismissed`, `PATCH
/vocabulary/{id}` `{"status": ...}`, `POST /vocabulary/status` `{"ids":
[...], "status": ...}`, `DELETE /vocabulary/{id}`. A word heard again
bumps `times_seen` and keeps its status. Words survive deleting the
conversation. Off: `vocabulary.enabled: false`.

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
