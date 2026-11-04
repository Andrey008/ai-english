package com.aienglish.companion.data.ws

/** Mirrors every server->client message in `server/app/ws_session.py`'s
 * documented protocol (`proto_version` 1), plus connection-lifecycle
 * events this client itself generates (reconnect attempts, giving up) —
 * those aren't part of the wire protocol, but callers need them to show a
 * real "reconnecting..." state instead of silence. */
sealed class WsEvent {
    data class SessionReady(val sessionId: String, val reconnected: Boolean) : WsEvent()

    data class SessionState(val state: SessionPhase) : WsEvent()

    data class TranscriptFinal(val text: String) : WsEvent()

    data class ResponseTextChunk(val text: String, val sentenceIndex: Int) : WsEvent()

    data class AudioChunkBoundary(val phase: BoundaryPhase, val sentenceIndex: Int) : WsEvent()

    /** One binary TTS PCM16 frame, tagged with the sentence it belongs to
     * (tracked client-side from the surrounding boundary events — the wire
     * frames themselves carry no sentence index). */
    data class AudioChunk(val sentenceIndex: Int, val pcm: ByteArray) : WsEvent()

    /** Non-fatal per protocol — a single turn's STT/TTS/LLM failure, not a
     * session-ending error. Callers should show it transiently, not tear
     * the session down. */
    data class ServerError(val message: String) : WsEvent()

    /** Clean server-acknowledged end (either the client sent `session_end`,
     * or the server closed the session for another reason after this). */
    data object SessionEnded : WsEvent()

    /** The socket dropped without a `session_ended` — connection lost, not
     * a clean end. A reconnect attempt follows unless the session was
     * explicitly ended. */
    data object ConnectionLost : WsEvent()

    data class Reconnecting(val attempt: Int) : WsEvent()

    /** Reconnect attempts exhausted — this client will not retry again on
     * its own; the caller must call [WsSessionClient.connect] again (which
     * starts a fresh session, since the server's reconnect grace window
     * has almost certainly passed by then). */
    data object ReconnectFailed : WsEvent()
}

enum class SessionPhase { LISTENING, PROCESSING, SPEAKING }

enum class BoundaryPhase { START, END }
