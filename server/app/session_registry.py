"""Single-slot session registry (STORY-02-05).

No multi-tenancy (ADR-0001) — at most one active/pending session at a
time. On a clean disconnect (not an explicit `session_end`), the slot is
kept for a grace window so a reconnecting client with the same
`session_id` can reattach to the still-live conversation history,
instead of `EPIC-08`'s full reconnect UX having to retrofit this at the
protocol level later.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

RECONNECT_GRACE_S = 60.0


class SessionConflictError(RuntimeError):
    pass


@dataclass
class SessionSlot:
    session_id: str
    connected: bool
    last_seen: float
    generation: int = 0
    owner: Any = None  # the live connection's websocket, for takeover


@dataclass
class ClaimResult:
    session_id: str
    is_reconnect: bool
    evicted_session_id: str | None
    generation: int = 0
    # Set on takeover: the still-"connected" previous socket for this same
    # session, which the caller must close.
    superseded_owner: Any = None


class SessionRegistry:
    def __init__(self) -> None:
        self._slot: SessionSlot | None = None
        self._generation = 0

    def try_claim(self, requested_session_id: str | None, owner: Any = None) -> ClaimResult:
        """Claim the single session slot.

        Raises `SessionConflictError` if another session is actively
        connected. `evicted_session_id`, if set, names a stale/unrelated
        session the caller must tear down engine-side state for (e.g.
        `ConversationEngine.end_session`).
        """
        now = time.monotonic()
        slot = self._slot
        self._generation += 1
        generation = self._generation

        if slot is not None and slot.connected:
            if requested_session_id != slot.session_id:
                raise SessionConflictError(f"session {slot.session_id!r} is already active")
            # Takeover: the same client reconnecting before the server
            # noticed its old socket died (a Mac sleep/wake or Wi-Fi roam
            # leaves it half-open for up to a ping timeout). Rejecting
            # with a conflict made the client back off for ~12s
            # (STORY-05-11); the session's own id is proof enough here
            # (single-user, ADR-0001).
            superseded = slot.owner
            slot.generation, slot.owner, slot.last_seen = generation, owner, now
            return ClaimResult(
                session_id=slot.session_id, is_reconnect=True, evicted_session_id=None,
                generation=generation, superseded_owner=superseded,
            )

        if (
            slot is not None
            and requested_session_id == slot.session_id
            and (now - slot.last_seen) <= RECONNECT_GRACE_S
        ):
            slot.connected = True
            slot.last_seen = now
            slot.generation, slot.owner = generation, owner
            return ClaimResult(
                session_id=slot.session_id, is_reconnect=True, evicted_session_id=None, generation=generation
            )

        evicted_id = slot.session_id if slot is not None else None
        new_id = requested_session_id or str(uuid.uuid4())
        self._slot = SessionSlot(
            session_id=new_id, connected=True, last_seen=now, generation=generation, owner=owner
        )
        return ClaimResult(
            session_id=new_id, is_reconnect=False, evicted_session_id=evicted_id, generation=generation
        )

    @property
    def held_session_id(self) -> str | None:
        """The session holding the slot (connected, or within its grace window)."""
        if self._slot is None:
            return None
        if not self._slot.connected and time.monotonic() - self._slot.last_seen > RECONNECT_GRACE_S:
            return None
        return self._slot.session_id

    def is_current(self, session_id: str, generation: int) -> bool:
        return (
            self._slot is not None
            and self._slot.session_id == session_id
            and self._slot.generation == generation
        )

    def release(self, session_id: str, generation: int | None = None) -> None:
        """Mark a session disconnected but keep its slot for the grace window.
        With `generation`, a no-op if a newer connection took the session over."""
        if generation is not None and not self.is_current(session_id, generation):
            return
        if self._slot is not None and self._slot.session_id == session_id:
            self._slot.connected = False
            self._slot.owner = None
            self._slot.last_seen = time.monotonic()

    def end(self, session_id: str) -> None:
        """Fully release the slot (explicit session_end, not just a disconnect)."""
        if self._slot is not None and self._slot.session_id == session_id:
            self._slot = None
