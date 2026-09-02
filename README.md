# AI English Voice Companion

Self-hosted, local-first, real-time voice conversation partner for practicing
spoken English. A macOS server (FastAPI + local VAD/STT/LLM/TTS) streams
audio with an Android client over a private network (Tailscale / Cloudflare
Tunnel). Single-user personal project.

## Stack (planned)

- **Backend:** Python 3.11+, FastAPI, async WebSockets, Silero VAD,
  Faster-Whisper, Ollama, Piper TTS / XTTS v2
- **Client:** Kotlin, Jetpack Compose, Android 14+
- **Networking:** Tailscale (or Cloudflare Tunnel)

## Project status & planning docs

All product/architecture/planning documentation (PRD, architecture,
roadmap, epics, stories, ADRs, status tracking) lives in `Docs/` on disk.
That folder is intentionally **not** version-controlled (see `.gitignore`) —
it's local working material for AI-assisted development, kept out of the
shipped-code repo on purpose.

If you're an AI assistant picking up this repo: read `CLAUDE.md`, then
`Docs/STATUS.md`, before doing anything else.

## Repo layout (target)

```
/server     Python FastAPI backend (from Phase 2)
/android    Kotlin/Compose client (from Phase 3)
/poc        Phase 1 CLI proof-of-concept scripts
Docs/       gitignored planning docs (local only)
```
