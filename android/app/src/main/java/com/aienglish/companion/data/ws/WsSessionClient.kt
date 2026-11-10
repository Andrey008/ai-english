package com.aienglish.companion.data.ws

import android.util.Log
import com.aienglish.companion.data.ServerConfigStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString
import java.util.concurrent.TimeUnit

private const val TAG = "WsSessionClient"
private const val PROTO_VERSION = 1
private val RECONNECT_BACKOFF_MS = listOf(1_000L, 2_000L, 4_000L, 8_000L, 16_000L, 32_000L)

/** No `pingInterval` means OkHttp never proactively probes an idle
 * WebSocket — discovered live (`STORY-05-05`): killing the server process
 * left the client's socket looking perfectly healthy from the client's
 * side for 2+ minutes with no data flowing either way, so nothing ever
 * triggered `onFailure`/`onClosed`. A dead mobile connection (radio idle,
 * NAT timeout) can silently drop the same way — pings are what turn a
 * silent failure into a detectable one. */
private fun defaultOkHttpClient(): OkHttpClient =
    OkHttpClient.Builder().pingInterval(15, TimeUnit.SECONDS).build()

/** `/ws/session` client (protocol documented in
 * `server/app/ws_session.py`'s module docstring). No UI dependency —
 * [events] is a hot [SharedFlow] so both the audio pipeline
 * (`STORY-05-06`) and the session UI (`STORY-05-07`) can observe it
 * independently. Reconnect/backoff is handled internally; callers only
 * see the resulting [WsEvent]s (`ConnectionLost`, `Reconnecting`,
 * `ReconnectFailed`, and whatever `session_ready.reconnected` the server
 * actually reports — this client relays that flag as-is rather than
 * guessing at continuity itself, per the protocol doc's known gap around
 * a server restart losing in-memory session state). */
class WsSessionClient(
    private val baseUrlProvider: suspend () -> String,
    private val httpClient: OkHttpClient = defaultOkHttpClient(),
) {
    constructor(serverConfigStore: ServerConfigStore, httpClient: OkHttpClient = defaultOkHttpClient()) : this(
        baseUrlProvider = {
            val config = serverConfigStore.configFlow.first()
            "http://${config.host}:${config.port}"
        },
        httpClient = httpClient,
    )

    private val json = Json { ignoreUnknownKeys = true }
    private val clientScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val _events = MutableSharedFlow<WsEvent>(extraBufferCapacity = 64)
    val events: SharedFlow<WsEvent> = _events.asSharedFlow()

    // STORY-05-10: Settings needs to know whether it's safe to repoint the
    // server address — changing it out from under a live session would
    // silently break the session's next reconnect attempt.
    private val _sessionActive = MutableStateFlow(false)
    val sessionActiveFlow: StateFlow<Boolean> = _sessionActive.asStateFlow()

    // Also STORY-05-10: found live while testing it — VoiceSessionScreen's
    // sessionPhase used to be plain remembered state, reset to null every
    // time the composable was recreated (e.g. switching bottom-nav tabs and
    // back), showing a stale/wrong phase for an already-running session
    // until the next event happened to arrive. A StateFlow lets a freshly
    // (re)composed screen — or anything else — read the *current* phase
    // immediately instead of waiting for the next push.
    private val _sessionPhase = MutableStateFlow<SessionPhase?>(null)
    val sessionPhaseFlow: StateFlow<SessionPhase?> = _sessionPhase.asStateFlow()

    @Volatile private var webSocket: WebSocket? = null
    // Only true between this socket's `session_ready` and its disconnect.
    // The mic streams continuously, and OkHttp queues anything sent before
    // the handshake completes — so without this gate, audio frames went out
    // *ahead of* `session_start` on every reconnect and the server rejected
    // the connection (STORY-05-11).
    @Volatile private var sessionReady = false
    @Volatile private var sessionId: String? = null
    @Volatile private var characterId: String? = null
    @Volatile private var scenarioId: String? = null
    @Volatile private var englishLevel: String? = null
    @Volatile private var useMemory: Boolean = true
    @Volatile private var currentAudioSentenceIndex: Int? = null
    @Volatile private var explicitlyEnded = true
    @Volatile private var reconnectAttempt = 0
    private var reconnectJob: Job? = null

    /** Starts a fresh session (no `session_id`) — always create mode, per
     * the protocol; reconnect is this client's own internal concern. */
    fun connect(
        characterId: String? = null,
        scenarioId: String? = null,
        englishLevel: String? = null,
        useMemory: Boolean = true,
    ) {
        this.characterId = characterId
        this.scenarioId = scenarioId
        this.englishLevel = englishLevel
        this.useMemory = useMemory
        this.sessionId = null
        explicitlyEnded = false
        reconnectAttempt = 0
        reconnectJob?.cancel()
        _sessionActive.value = true
        _sessionPhase.value = null
        openSocket()
    }

    /** Raw PCM16/16kHz/mono bytes, any chunk size — chunking policy is
     * `STORY-05-06`'s job, this is just the wire-send interface. Silently
     * dropped if not currently connected (no buffering — stale audio from
     * a dead connection has no value). */
    fun sendAudio(pcm: ByteArray) {
        if (!sessionReady) return
        webSocket?.send(pcm.toByteString())
    }

    fun endSession() {
        explicitlyEnded = true
        reconnectJob?.cancel()
        _sessionActive.value = false
        _sessionPhase.value = null
        webSocket?.send(buildJsonObject { put("type", "session_end") }.toString())
    }

    /** Unconditional teardown — cancels any in-flight reconnect attempt,
     * drops the socket without a clean `session_end` handshake (the
     * server sees this as a disconnect, releasing its session slot for
     * the grace window, not a full end), and cancels this client's
     * internal coroutine scope. For discarding an instance outright (e.g.
     * a test's per-case client); the long-lived [AppContainer] singleton
     * has no reason to call this during normal operation. */
    fun close() {
        explicitlyEnded = true
        reconnectJob?.cancel()
        _sessionActive.value = false
        _sessionPhase.value = null
        webSocket?.cancel()
        webSocket = null
        clientScope.cancel()
    }

    private fun openSocket() {
        clientScope.launch {
            val url = baseUrlProvider().replaceFirst("http", "ws") + "/ws/session"
            val request = Request.Builder().url(url).build()
            sessionReady = false
            Log.i(TAG, "opening socket to $url (attempt=$reconnectAttempt)")
            webSocket = httpClient.newWebSocket(request, Listener())
        }
    }

    private inner class Listener : WebSocketListener() {
        /** A replaced socket's late callbacks must not tear down the
         * current one (they used to null out [webSocket] and schedule a
         * second, overlapping reconnect). */
        private fun isStale(socket: WebSocket): Boolean {
            val current = this@WsSessionClient.webSocket
            return current != null && current !== socket
        }

        override fun onOpen(webSocket: WebSocket, response: Response) {
            Log.i(TAG, "socket open")
            val payload = buildJsonObject {
                put("type", "session_start")
                put("proto_version", PROTO_VERSION)
                val currentSessionId = sessionId
                if (currentSessionId != null) {
                    put("session_id", currentSessionId)
                } else {
                    characterId?.let { put("character_id", it) }
                    scenarioId?.let { put("scenario_id", it) }
                    englishLevel?.let { put("english_level", it) }
                    put("use_memory", useMemory)
                }
            }
            webSocket.send(payload.toString())
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            handleTextMessage(text)
        }

        override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
            val index = currentAudioSentenceIndex ?: return
            clientScope.launch { _events.emit(WsEvent.AudioChunk(index, bytes.toByteArray())) }
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            Log.w(TAG, "server closing socket: code=$code reason=$reason")
            webSocket.close(1000, null)
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            Log.w(TAG, "socket closed: code=$code reason=$reason stale=${isStale(webSocket)}")
            if (isStale(webSocket)) return
            handleDisconnect()
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            Log.w(TAG, "socket failure (stale=${isStale(webSocket)}, http=${response?.code})", t)
            if (isStale(webSocket)) return
            handleDisconnect()
        }
    }

    private fun handleTextMessage(text: String) {
        val obj = json.parseToJsonElement(text).jsonObject
        val type = obj["type"]?.jsonPrimitive?.content ?: return
        val event = when (type) {
            "session_ready" -> {
                val id = obj["session_id"]?.jsonPrimitive?.content ?: return
                sessionId = id
                reconnectAttempt = 0
                sessionReady = true
                Log.i(TAG, "session_ready id=$id reconnected=${obj["reconnected"]}")
                WsEvent.SessionReady(id, obj["reconnected"]?.jsonPrimitive?.boolean ?: false)
            }
            "session_state" -> {
                val phase = when (obj["state"]?.jsonPrimitive?.content) {
                    "listening" -> SessionPhase.LISTENING
                    "processing" -> SessionPhase.PROCESSING
                    "speaking" -> SessionPhase.SPEAKING
                    else -> return
                }
                _sessionPhase.value = phase
                WsEvent.SessionState(phase)
            }
            "transcript_final" -> WsEvent.TranscriptFinal(obj["text"]?.jsonPrimitive?.content ?: return)
            "response_text_chunk" -> WsEvent.ResponseTextChunk(
                obj["text"]?.jsonPrimitive?.content ?: return,
                obj["sentence_index"]?.jsonPrimitive?.int ?: return,
            )
            "audio_chunk_boundary" -> {
                val sentenceIndex = obj["sentence_index"]?.jsonPrimitive?.int ?: return
                val phase = if (obj["phase"]?.jsonPrimitive?.content == "start") BoundaryPhase.START else BoundaryPhase.END
                currentAudioSentenceIndex = if (phase == BoundaryPhase.START) sentenceIndex else null
                WsEvent.AudioChunkBoundary(phase, sentenceIndex)
            }
            "error" -> WsEvent.ServerError(obj["message"]?.jsonPrimitive?.content ?: "unknown error")
            "session_ended" -> WsEvent.SessionEnded
            else -> return
        }
        clientScope.launch { _events.emit(event) }
    }

    private fun handleDisconnect() {
        val wasConnected = reconnectAttempt == 0
        sessionReady = false
        webSocket = null
        Log.i(TAG, "disconnect: explicitlyEnded=$explicitlyEnded attempt=$reconnectAttempt")
        currentAudioSentenceIndex = null
        if (explicitlyEnded) return

        if (wasConnected) {
            clientScope.launch { _events.emit(WsEvent.ConnectionLost) }
        }
        if (reconnectAttempt >= RECONNECT_BACKOFF_MS.size) {
            Log.w(TAG, "giving up after $reconnectAttempt reconnect attempts")
            _sessionActive.value = false
            _sessionPhase.value = null
            clientScope.launch { _events.emit(WsEvent.ReconnectFailed) }
            return
        }
        val delayMs = RECONNECT_BACKOFF_MS[reconnectAttempt]
        reconnectAttempt += 1
        val attemptNumber = reconnectAttempt
        reconnectJob = clientScope.launch {
            delay(delayMs)
            if (explicitlyEnded) return@launch
            _events.emit(WsEvent.Reconnecting(attemptNumber))
            openSocket()
        }
    }
}
