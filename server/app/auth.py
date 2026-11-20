"""Per-device bearer-token auth for every HTTP and WebSocket route (ADR-0017).

A client sends `Authorization: Bearer <token>` on each HTTP request and on
the WebSocket upgrade. The token is never accepted from a query string:
URLs end up in proxy and tunnel logs, and a browser page can't set this
header on a WebSocket, which also rules out cross-site WebSocket hijacking.

Tokens are 256-bit random strings, so a plain SHA-256 is enough to store
them (no slow hash needed: there is nothing to brute-force).
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
from typing import Any

logger = logging.getLogger("ai_english.auth")

TOKEN_PREFIX = "aie_"
# Reachable without a token: liveness probes (tunnel / uptime checks).
# Says nothing beyond "a server is here".
PUBLIC_PATHS = frozenset({"/healthz"})
# Write `last_used_at` at most this often per device.
TOUCH_INTERVAL_S = 60.0


def generate_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def config_flag(value: Any, default: bool) -> bool:
    """YAML gives a bool, an env override gives a string ("false")."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off", ""}


def bearer_token(headers: list[tuple[bytes, bytes]]) -> str | None:
    for name, value in headers:
        if name.lower() != b"authorization":
            continue
        scheme, _, token = value.decode("latin-1").strip().partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            return token.strip()
    return None


def client_address(scope: dict) -> str | None:
    """Real client IP: a reverse proxy connects from loopback."""
    for name, value in scope.get("headers", []):
        if name.lower() in (b"cf-connecting-ip", b"x-forwarded-for"):
            return value.decode("latin-1").split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else None


class AuthMiddleware:
    """Pure ASGI middleware (works for both `http` and `websocket` scopes).
    Looks the token up in the DB on every request, so `scripts/devices.py
    revoke` takes effect without restarting the server."""

    def __init__(self, app, db_getter, enabled: bool = True):
        self.app = app
        self._db_getter = db_getter
        self._enabled = enabled
        self._last_touch: dict[str, float] = {}

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket") or not self._enabled:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "http" and scope["path"] in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        token = bearer_token(scope.get("headers", []))
        device = None
        if token is not None:
            device = await self._db_getter().get_device_by_token_hash(hash_token(token))
        if device is None or device["revoked_at"] is not None:
            reason = "missing_token" if token is None else ("revoked" if device else "unknown_token")
            logger.warning(
                "auth_rejected",
                extra={"path": scope["path"], "scope_type": scope["type"],
                       "reason": reason, "client_ip": client_address(scope)},
            )
            await _deny(scope, receive, send)
            return

        scope.setdefault("state", {})["device"] = {"id": device["id"], "name": device["name"]}
        await self._touch(device["id"])
        await self.app(scope, receive, send)

    async def _touch(self, device_id: str) -> None:
        now = time.monotonic()
        if now - self._last_touch.get(device_id, -TOUCH_INTERVAL_S) < TOUCH_INTERVAL_S:
            return
        self._last_touch[device_id] = now
        try:
            await self._db_getter().touch_device(device_id)
        except Exception:
            logger.exception("auth_touch_failed")


async def _deny(scope, receive, send) -> None:
    body = json.dumps({"detail": "unauthorized"}).encode()
    headers = [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")]
    if scope["type"] == "http":
        await send({"type": "http.response.start", "status": 401, "headers": headers})
        await send({"type": "http.response.body", "body": body})
        return
    # WebSocket: answer the upgrade with a plain HTTP 401 where the server
    # supports it, so the client can tell "bad token" from "network down"
    # and stop reconnecting. Otherwise uvicorn turns the close into a 403.
    message = await receive()
    if message["type"] != "websocket.connect":
        return
    if "websocket.http.response" in scope.get("extensions", {}):
        await send({"type": "websocket.http.response.start", "status": 401, "headers": headers})
        await send({"type": "websocket.http.response.body", "body": body})
    else:
        await send({"type": "websocket.close", "code": 1008})
