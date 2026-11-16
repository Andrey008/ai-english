"""FastAPI app factory."""
from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI, HTTPException, Request, WebSocket
from pydantic import BaseModel, Field

from app.auth import AuthMiddleware, config_flag
from app.character_memory import CharacterMemoryService
from app.claude_gateway import ClaudeGateway
from app.config import get_config
from app.conversation_engine import ConversationEngine
from app.db import Database
from app.interview.prep_client import PrepClient, PrepUnavailable
from app.interview.translation import translate_missing
from app.logging_setup import configure_logging
from app.presets import CharacterPreset, PresetExistsError, PresetNotFoundError, PresetStore
from app.scenarios import ScenarioDefinition, ScenarioExistsError, ScenarioNotFoundError, ScenarioStore
from app.session_registry import SessionRegistry
from app.stt_service import STTService
from app.tts_service import TTSService
from app.ws_session import handle_ws_session

logger = logging.getLogger("ai_english.server")


def create_app() -> FastAPI:
    configure_logging()
    config = get_config()
    security = config.get("security") or {}
    # API docs list every route for whoever finds the server: off unless
    # asked for (ADR-0017).
    docs = config_flag(security.get("api_docs"), default=False)
    app = FastAPI(
        title="AI English Voice Companion — Server",
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.config = config
    auth_required = config_flag(security.get("auth_required"), default=True)
    app.add_middleware(AuthMiddleware, db_getter=lambda: app.state.db, enabled=auth_required)
    if not auth_required:
        logger.warning("auth_disabled", extra={"hint": "every route is open to anyone who can reach the port"})
    app.state.stt_service = STTService(config)
    app.state.tts_service = TTSService(config)
    app.state.conversation_engine = ConversationEngine(config)
    app.state.session_registry = SessionRegistry()
    app.state.db = Database(config)
    app.state.preset_store = PresetStore(config)
    app.state.scenario_store = ScenarioStore(config)
    app.state.character_memory_service = CharacterMemoryService(config, app.state.db)
    app.state.claude_gateway = ClaudeGateway(config)
    app.state.prep_client = PrepClient(config)
    app.state.background_tasks = set()
    app.state.interviews = {}  # session_id → InterviewState (survives a reconnect)

    async def translate_prep_questions() -> None:
        """EPIC-10: fill the RU→EN question cache in the background.
        Missing prep or gateway is not an error for the server."""
        try:
            base = await app.state.prep_client.fetch()
            await translate_missing(base.questions, app.state.db, app.state.claude_gateway)
        except PrepUnavailable as exc:
            logger.info("interview_translation_skipped", extra={"reason": str(exc)})
        except Exception:
            logger.exception("interview_translation_error")

    @app.on_event("startup")
    async def on_startup() -> None:
        logger.info(
            "server_startup",
            extra={
                "stt_engine": config["stt"]["engine"],
                "llm_model": config["llm"]["model"],
                "tts_engine": config["tts"]["engine"],
            },
        )
        await app.state.db.start()
        await app.state.stt_service.start()
        await app.state.tts_service.start()
        await app.state.conversation_engine.check_ready()
        logger.info("conversation_engine_ready", extra={"model": config["llm"]["model"]})
        app.state.preset_store.ensure_seed()
        logger.info("preset_store_ready", extra={"count": len(app.state.preset_store.list())})
        if app.state.claude_gateway.configured:
            task = asyncio.create_task(translate_prep_questions())
            app.state.background_tasks.add(task)
            task.add_done_callback(app.state.background_tasks.discard)
        else:
            logger.info("claude_gateway_not_configured")

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        await app.state.stt_service.stop()
        await app.state.tts_service.stop()
        await app.state.db.stop()

    @app.get("/healthz")
    async def healthz() -> dict:
        logger.info("healthz_check")
        return {"status": "ok"}

    @app.get("/auth/me")
    async def auth_me(request: Request) -> dict:
        """The device this token belongs to. Clients call it to check the
        server address and token together."""
        device = getattr(request.state, "device", None)
        return {"device": device, "auth_required": auth_required}

    @app.websocket("/ws/session")
    async def ws_session(websocket: WebSocket) -> None:
        await handle_ws_session(websocket)

    @app.post("/characters", status_code=201)
    async def create_character(preset: CharacterPreset) -> CharacterPreset:
        try:
            return app.state.preset_store.create(preset)
        except PresetExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/characters")
    async def list_characters() -> list[CharacterPreset]:
        return app.state.preset_store.list()

    @app.get("/characters/{character_id}")
    async def get_character(character_id: str) -> CharacterPreset:
        preset = app.state.preset_store.get(character_id)
        if preset is None:
            raise HTTPException(status_code=404, detail=f"character {character_id!r} not found")
        return preset

    @app.put("/characters/{character_id}")
    async def update_character(character_id: str, preset: CharacterPreset) -> CharacterPreset:
        try:
            return app.state.preset_store.update(character_id, preset)
        except PresetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/characters/{character_id}", status_code=204)
    async def delete_character(character_id: str) -> None:
        if not app.state.preset_store.delete(character_id):
            raise HTTPException(status_code=404, detail=f"character {character_id!r} not found")

    @app.delete("/characters/{character_id}/memory", status_code=204)
    async def delete_character_memory(character_id: str) -> None:
        if app.state.preset_store.get(character_id) is None:
            raise HTTPException(status_code=404, detail=f"character {character_id!r} not found")
        await app.state.db.delete_character_memory(character_id)

    @app.get("/conversations")
    async def list_conversations() -> list[dict]:
        """Past conversations (ADR-0015), most recently active first."""
        active = app.state.session_registry.held_session_id
        rows = await app.state.db.list_conversations()
        return [conversation_summary(row, app.state.preset_store, active) for row in rows]

    @app.get("/conversations/{session_id}")
    async def get_conversation(session_id: str) -> dict:
        row = await app.state.db.get_session(session_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"conversation {session_id!r} not found")
        turns = await app.state.db.get_transcript(session_id)
        user_turns = [t for t in turns if t["role"] == "user"]
        summary = conversation_summary(
            {**row, "turns": len(turns), "user_turns": len(user_turns),
             "last_turn_at": turns[-1]["ts"] if turns else None,
             "topic": user_turns[0]["text"] if user_turns else None},
            app.state.preset_store, app.state.session_registry.held_session_id,
        )
        return {**summary, "transcript": turns}

    @app.patch("/conversations/{session_id}")
    async def rename_conversation(session_id: str, body: ConversationRename) -> dict:
        """The user's own title; later wrap-ups keep it."""
        if not await app.state.db.rename_session(session_id, " ".join(body.title.split())):
            raise HTTPException(status_code=404, detail=f"conversation {session_id!r} not found")
        return await get_conversation(session_id)

    @app.delete("/conversations/{session_id}", status_code=204)
    async def delete_conversation(session_id: str) -> None:
        if app.state.session_registry.held_session_id == session_id:
            raise HTTPException(status_code=409, detail="conversation is active")
        if not await app.state.db.delete_session(session_id):
            raise HTTPException(status_code=404, detail=f"conversation {session_id!r} not found")

    @app.post("/scenarios", status_code=201)
    async def create_scenario(scenario: ScenarioDefinition) -> ScenarioDefinition:
        try:
            return app.state.scenario_store.create(scenario)
        except ScenarioExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/scenarios")
    async def list_scenarios() -> list[ScenarioDefinition]:
        return app.state.scenario_store.list()

    @app.get("/scenarios/{scenario_id}")
    async def get_scenario(scenario_id: str) -> ScenarioDefinition:
        scenario = app.state.scenario_store.get(scenario_id)
        if scenario is None:
            raise HTTPException(status_code=404, detail=f"scenario {scenario_id!r} not found")
        return scenario

    @app.put("/scenarios/{scenario_id}")
    async def update_scenario(scenario_id: str, scenario: ScenarioDefinition) -> ScenarioDefinition:
        try:
            return app.state.scenario_store.update(scenario_id, scenario)
        except ScenarioNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/scenarios/{scenario_id}", status_code=204)
    async def delete_scenario(scenario_id: str) -> None:
        if not app.state.scenario_store.delete(scenario_id):
            raise HTTPException(status_code=404, detail=f"scenario {scenario_id!r} not found")

    return app


TOPIC_MAX_CHARS = 80


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=120, pattern=r"\S")


def conversation_summary(row: dict, preset_store: PresetStore, active_session_id: str | None) -> dict:
    """One `/conversations` list item. `title` comes from the wrap-up
    (ADR-0015); older rows only have `topic`, the first user line.
    A conversation whose character was deleted can't be continued."""
    preset = preset_store.get(row["character_id"]) if row.get("character_id") else None
    topic = " ".join((row.get("topic") or "").split())
    if len(topic) > TOPIC_MAX_CHARS:
        topic = topic[:TOPIC_MAX_CHARS].rsplit(" ", 1)[0] + "…"
    return {
        "id": row["id"],
        "character_id": row.get("character_id"),
        "character_name": preset.name if preset else None,
        "scenario_id": row.get("scenario_id"),
        "english_level": row.get("english_level"),
        "title": row.get("title"),
        "topic": topic or None,
        "started_at": row["started_at"],
        "last_turn_at": row.get("last_turn_at"),
        "turns": row.get("turns", 0),
        "user_turns": row.get("user_turns", 0),
        "active": row["id"] == active_session_id,
        "can_resume": preset is not None or not row.get("character_id"),
    }


app = create_app()
