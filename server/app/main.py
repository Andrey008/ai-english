"""FastAPI app factory."""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, WebSocket

from app.character_memory import CharacterMemoryService
from app.config import get_config
from app.conversation_engine import ConversationEngine
from app.db import Database
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
    app = FastAPI(title="AI English Voice Companion — Server")
    app.state.config = config
    app.state.stt_service = STTService(config)
    app.state.tts_service = TTSService(config)
    app.state.conversation_engine = ConversationEngine(config)
    app.state.session_registry = SessionRegistry()
    app.state.db = Database(config)
    app.state.preset_store = PresetStore(config)
    app.state.scenario_store = ScenarioStore(config)
    app.state.character_memory_service = CharacterMemoryService(config, app.state.db)

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

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        await app.state.stt_service.stop()
        await app.state.tts_service.stop()
        await app.state.db.stop()

    @app.get("/healthz")
    async def healthz() -> dict:
        logger.info("healthz_check")
        return {"status": "ok"}

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


app = create_app()
