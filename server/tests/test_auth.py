"""ADR-0017: per-device bearer tokens on HTTP and WebSocket routes."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI, Request, WebSocket
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDenialResponse

from app.auth import AuthMiddleware, bearer_token, config_flag, generate_token, hash_token
from app.db import Database


@pytest.fixture
def db(tmp_path):
    database = Database({"persistence": {"db_path": str(tmp_path / "test.db")}})
    asyncio.run(database.start())
    yield database
    asyncio.run(database.stop())


def _client(db: Database, enabled: bool = True) -> TestClient:
    app = FastAPI()
    app.add_middleware(AuthMiddleware, db_getter=lambda: db, enabled=enabled)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/private")
    async def private(request: Request) -> dict:
        return {"device": getattr(request.state, "device", None)}

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_json({"device": websocket.state.device})
        await websocket.close()

    return TestClient(app)


def _new_device(db: Database, name: str = "phone") -> tuple[dict, str]:
    token = generate_token()
    device = asyncio.run(db.create_device(name, hash_token(token)))
    return device, token


def test_http_needs_a_valid_token(db):
    _, token = _new_device(db)
    client = _client(db)
    assert client.get("/private").status_code == 401
    assert client.get("/private", headers={"Authorization": "Bearer aie_wrong"}).status_code == 401
    assert client.get("/private", headers={"Authorization": f"Basic {token}"}).status_code == 401
    ok = client.get("/private", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200
    assert ok.json()["device"]["name"] == "phone"


def test_token_in_query_string_is_not_accepted(db):
    _, token = _new_device(db)
    assert _client(db).get(f"/private?token={token}").status_code == 401


def test_healthz_is_public(db):
    assert _client(db).get("/healthz").status_code == 200


def test_revoked_token_stops_working_without_restart(db):
    device, token = _new_device(db)
    client = _client(db)
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/private", headers=headers).status_code == 200
    assert asyncio.run(db.revoke_device(device["id"])) is True
    assert client.get("/private", headers=headers).status_code == 401
    assert asyncio.run(db.revoke_device(device["id"])) is False


def test_websocket_upgrade_is_refused_with_401(db):
    _, token = _new_device(db)
    client = _client(db)
    with pytest.raises(WebSocketDenialResponse) as exc:
        with client.websocket_connect("/ws"):
            pass
    assert exc.value.status_code == 401
    with client.websocket_connect("/ws", headers={"Authorization": f"Bearer {token}"}) as ws:
        assert ws.receive_json()["device"]["name"] == "phone"


def test_last_used_is_recorded(db):
    device, token = _new_device(db)
    assert device["last_used_at"] is None
    _client(db).get("/private", headers={"Authorization": f"Bearer {token}"})
    assert asyncio.run(db.get_device(device["id"]))["last_used_at"] is not None


def test_disabled_auth_lets_everything_through(db):
    assert _client(db, enabled=False).get("/private").status_code == 200


def test_only_the_hash_is_stored(db):
    device, token = _new_device(db)
    assert token not in str(device)
    assert device["token_hash"] == hash_token(token)


def test_tokens_are_long_and_unique():
    tokens = {generate_token() for _ in range(100)}
    assert len(tokens) == 100
    assert all(t.startswith("aie_") and len(t) >= 40 for t in tokens)


def test_bearer_parsing():
    assert bearer_token([(b"authorization", b"Bearer abc")]) == "abc"
    assert bearer_token([(b"Authorization", b"bearer  abc ")]) == "abc"
    assert bearer_token([(b"authorization", b"Bearer ")]) is None
    assert bearer_token([]) is None


@pytest.mark.parametrize("value,expected", [
    (None, True), (True, True), (False, False), ("false", False), ("0", False),
    ("off", False), ("true", True), ("1", True),
])
def test_config_flag(value, expected):
    assert config_flag(value, default=True) is expected


def test_real_app_requires_auth_and_hides_docs():
    from app.main import create_app

    app = create_app()
    client = TestClient(app)  # no lifespan: models stay unloaded
    assert client.get("/healthz").status_code == 200
    assert client.get("/characters").status_code == 401
    assert client.get("/conversations").status_code == 401
    assert client.get("/auth/me").status_code == 401
    assert app.docs_url is None and app.openapi_url is None and app.redoc_url is None
