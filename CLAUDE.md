# Project Instructions for AI Assistants

## First action, every session

Read `Docs/STATUS.md` before doing anything else. It says what phase/epic/
story is active, what's done, what's next, and lists open questions. Then
read the relevant epic/story file(s) it points to.

## What this project is

A self-hosted, single-user, real-time voice conversation partner for
practicing spoken English. macOS server (FastAPI, local VAD/STT/LLM/TTS
streaming pipeline) + Android client, connected over Tailscale. Full
context: `Docs/PRD.md` and `Docs/ARCHITECTURE.md`.

## Documentation system (read this before touching Docs/)

- `Docs/` is **gitignored on purpose** — it's local planning material for
  AI-assisted development, not shipped product code. It must never be
  committed. Everything else at the repo root (code, configs, this file)
  is committed normally.
- `Docs/STATUS.md` is the single source of truth for "where are we." Update
  it whenever you complete a story, change a decision, or hit a blocker —
  don't let it go stale within a session.
- `Docs/ROADMAP.md` lists all phases/epics and their status at a glance.
- `Docs/epics/EPIC-NN-*.md` — one file per epic (goal, scope, acceptance
  criteria, dependencies, status). Only **Phase 1 (EPIC-01)** currently has
  epic-level detail broken into stories — the rest are intentionally
  high-level until their phase is about to start (see
  `Docs/ROADMAP.md` → "Detailing policy").
- `Docs/stories/epic-NN/STORY-*.md` — per-story task breakdown + acceptance
  criteria + status, for epics that have been detailed.
- `Docs/decisions/ADR-*.md` — architecture decision records. Add one
  whenever a non-obvious, hard-to-reverse technical decision is made.
- `Docs/handoff/CURRENT_HANDOFF.md` — the copy-pasteable context block for
  starting the next chat session. Regenerate it before ending a session
  whenever you're handing off to a new chat.

## Workflow rules

1. **One phase per chat session** (occasionally one epic, if a phase has
   several large independent epics) — don't try to span multiple phases in
   a single context window; this avoids context bloat and hallucination
   drift on a long-running project.
2. Before ending a session that will hand off to a new chat: update
   `Docs/STATUS.md`, mark finished stories, and rewrite
   `Docs/handoff/CURRENT_HANDOFF.md` with what the next chat needs to know.
   Print that handoff block in the chat too, so the user can paste it.
3. Detail a phase's stories **just before starting that phase**, in a short
   dedicated planning pass — not all upfront. This keeps early plans from
   going stale before we learn things from earlier phases (especially
   Phase 1 PoC findings).
4. This is a **single-user, personal, local-first** system. Do not add
   multi-tenant, auth-server, or cloud-hosting complexity unless the user
   explicitly asks for it.
5. The latency budget in `Docs/PRD.md` (TTFA ≤ 1.5s end-to-end) is a hard
   constraint from the original spec — validate any pipeline change against
   it, and update the budget in the PRD (with an ADR) if reality forces a
   change.
6. The **learning-progress layer is optional/configurable** — it must never
   get in the way of the core experience (an engaging, proactive
   conversational partner). If in doubt, ship the conversational value
   first, learning analytics second.
7. **Barge-in (voice interruption) is conditional** on the Phase 1 PoC
   resource-feasibility finding (see EPIC-01 / STORY-01-07). Don't assume
   it's in scope until that story's decision is recorded.
8. Be self-critical: if you spot a gap, risk, or over-engineered corner
   while implementing, raise it — don't silently build around it. Log real
   decisions as ADRs, not just in chat.

## Repo layout (target)

```
/server     Python FastAPI backend (from Phase 2)
/android    Kotlin/Compose client (from Phase 3)
/poc        Phase 1 CLI proof-of-concept scripts
Docs/       gitignored planning docs (see above)
```
