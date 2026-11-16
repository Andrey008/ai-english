package com.aienglish.companion.data.ws

import com.aienglish.companion.data.ServerConfig
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.WebSocket
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * Live verification for STORY-05-05 — requires a real `/server` reachable
 * at `127.0.0.1:8000` (`uv run uvicorn app.main:app --host 127.0.0.1
 * --port 8000` from `/server`). Plain JVM test, not an instrumented one:
 * [WsSessionClient]'s primary constructor has zero Android dependencies
 * (OkHttp + kotlinx.serialization + kotlinx.coroutines only), so this runs
 * via `./gradlew test` directly against the dev machine's own server —
 * faster than a device/emulator round-trip and just as real a check of
 * the client's networking stack. Not CI-safe, same convention as
 * `ApiClientLiveTest`. Assumes the Gradle `test` task's working directory
 * is `android/app` (the default), hence the `../../` paths below.
 */
/** Token from `server/scripts/devices.py create`, via `AI_ENGLISH_TOKEN`. */
private val LOCAL_SERVER = ServerConfig(
    host = "127.0.0.1", port = 8000, token = System.getenv("AI_ENGLISH_TOKEN").orEmpty(),
)

class WsSessionClientLiveTest {

    private val wavFile = File("../../poc/samples/test_input.wav")

    private fun loadPcmWithTrailingSilence(): ByteArray {
        val bytes = wavFile.readBytes()
        // Standard 44-byte canonical PCM WAV header — same assumption
        // server/scripts/ws_test_client.py's `wave` module reading makes
        // implicitly for this project's own recorded samples.
        val pcm = bytes.copyOfRange(44, bytes.size)
        val trailingSilence = ByteArray((16_000 * 1.5 * 2).toInt())
        return pcm + trailingSilence
    }

    private suspend fun <T> awaitEvent(
        events: List<WsEvent>,
        timeoutMs: Long = 20_000,
        predicate: (WsEvent) -> T?,
    ): T = withTimeout(timeoutMs) {
        var result: T? = events.firstNotNullOfOrNull(predicate)
        while (result == null) {
            delay(50)
            result = events.firstNotNullOfOrNull(predicate)
        }
        result
    }

    private fun collectEvents(client: WsSessionClient, scope: CoroutineScope): Pair<MutableList<WsEvent>, Job> {
        val events = mutableListOf<WsEvent>()
        val job = scope.launch { client.events.collect { events.add(it) } }
        return events to job
    }

    @Test
    fun fullTurn_roundTrip() = runBlocking {
        val client = WsSessionClient(configProvider = { LOCAL_SERVER })
        val scope = CoroutineScope(Dispatchers.IO)
        val (events, job) = collectEvents(client, scope)
        try {
            client.connect()
            val ready = awaitEvent(events) { it as? WsEvent.SessionReady }
            assertTrue("expected a fresh session, got reconnected=true", !ready.reconnected)

            val pcm = loadPcmWithTrailingSilence()
            val chunkBytes = (16_000 * 0.1 * 2).toInt()
            var offset = 0
            while (offset < pcm.size) {
                val end = minOf(offset + chunkBytes, pcm.size)
                client.sendAudio(pcm.copyOfRange(offset, end))
                offset = end
                delay(100)
            }

            // Generous timeouts: qwen2.5:32b may need a cold load into
            // Ollama on the first real generate call of a fresh server
            // process (STORY-01-02 measured this in the hundreds-of-
            // seconds range in the worst case) — this is a live check
            // against real infra, not a mocked, deterministic unit test.
            val transcript = awaitEvent(events, timeoutMs = 90_000) { it as? WsEvent.TranscriptFinal }
            assertTrue("expected non-blank transcript", transcript.text.isNotBlank())

            val chunk = awaitEvent(events, timeoutMs = 90_000) { it as? WsEvent.ResponseTextChunk }
            assertTrue("expected non-blank reply text", chunk.text.isNotBlank())

            awaitEvent(events, timeoutMs = 30_000) { e -> (e as? WsEvent.AudioChunkBoundary)?.takeIf { it.phase == BoundaryPhase.END } }
            awaitEvent(events) { e -> (e as? WsEvent.AudioChunk)?.takeIf { it.pcm.isNotEmpty() } }
            awaitEvent(events) { e -> (e as? WsEvent.SessionState)?.takeIf { it.state == SessionPhase.LISTENING } }

            client.endSession()
            awaitEvent(events) { if (it is WsEvent.SessionEnded) Unit else null }
        } finally {
            // Unconditional, even on assertion failure — the server allows
            // only one active session at a time (ADR-0001), so a dangling
            // connection left open by a failed assertion here breaks every
            // *other* test in this class, not just this one. (Found live:
            // an assertion failure before `endSession()` left this test's
            // socket connected server-side, and the next test's `connect()`
            // then retried against a permanently "busy" slot until it
            // timed out.)
            client.close()
            job.cancel()
        }
    }

    @Test
    fun scenarioId_opensWithExactHintBeforeListening() = runBlocking {
        val client = WsSessionClient(configProvider = { LOCAL_SERVER })
        val scope = CoroutineScope(Dispatchers.IO)
        val (events, job) = collectEvents(client, scope)
        try {
            // small_talk_neighbor's opening_line_hint (server/data/scenarios) —
            // spoken verbatim (not LLM-generated), so this is a deterministic
            // check, unlike freeform reply content.
            val expectedOpeningLine = "Oh hey, good to see you! Have you been enjoying this weather we have been having?"

            client.connect(scenarioId = "small_talk_neighbor")
            awaitEvent(events) { it as? WsEvent.SessionReady }

            // The opening line is spoken as static text, sentence-chunked
            // the same way a normal LLM reply is (`_speak_text` in
            // ws_session.py) — so it can arrive as more than one
            // `response_text_chunk` event. Wait for the first
            // `listening` state (everything before it is the proactive
            // opening), then reconstruct the full line from every chunk
            // that preceded it, in order.
            awaitEvent(events) { e -> (e as? WsEvent.SessionState)?.takeIf { it.state == SessionPhase.LISTENING } }
            val listeningIndex = events.indexOfFirst { it is WsEvent.SessionState && it.state == SessionPhase.LISTENING }
            val openingChunks = events.subList(0, listeningIndex).filterIsInstance<WsEvent.ResponseTextChunk>()
            assertTrue("expected at least one response_text_chunk before listening", openingChunks.isNotEmpty())
            assertEquals(expectedOpeningLine, openingChunks.joinToString(" ") { it.text })

            client.endSession()
            awaitEvent(events) { if (it is WsEvent.SessionEnded) Unit else null }
        } finally {
            // Unconditional, even on assertion failure — the server allows
            // only one active session at a time (ADR-0001), so a dangling
            // connection left open by a failed assertion here breaks every
            // *other* test in this class, not just this one. (Found live:
            // an assertion failure before `endSession()` left this test's
            // socket connected server-side, and the next test's `connect()`
            // then retried against a permanently "busy" slot until it
            // timed out.)
            client.close()
            job.cancel()
        }
    }

    @Test
    fun reconnect_withinGraceWindow_resumesSameSession() = runBlocking {
        val client = WsSessionClient(configProvider = { LOCAL_SERVER })
        val scope = CoroutineScope(Dispatchers.IO)
        val (events, job) = collectEvents(client, scope)
        try {
            client.connect()
            val firstReady = awaitEvent(events) { it as? WsEvent.SessionReady }
            assertTrue(!firstReady.reconnected)

            // Simulate a network drop: abruptly cancel the live socket
            // (no close frame) rather than a clean session_end, so the
            // server sees a disconnect, not an explicit end, and keeps the
            // session slot for its reconnect grace window
            // (`SessionRegistry.RECONNECT_GRACE_S`). Reflection is
            // test-only plumbing — WsSessionClient's public API has no
            // "simulate a dead connection" hook, deliberately, since real
            // callers never need one.
            val field = WsSessionClient::class.java.getDeclaredField("webSocket")
            field.isAccessible = true
            val socket = requireNotNull(field.get(client) as? WebSocket) {
                "expected an active WebSocket after session_ready"
            }
            socket.cancel()

            awaitEvent(events) { if (it is WsEvent.ConnectionLost) Unit else null }
            awaitEvent(events) { it as? WsEvent.Reconnecting }

            val secondReady = awaitEvent(events, timeoutMs = 30_000) {
                (it as? WsEvent.SessionReady)?.takeIf { ready -> ready !== firstReady }
            }
            assertTrue("expected reconnected=true within the grace window", secondReady.reconnected)
            assertEquals(firstReady.sessionId, secondReady.sessionId)

            client.endSession()
            awaitEvent(events) { if (it is WsEvent.SessionEnded) Unit else null }
        } finally {
            // Unconditional, even on assertion failure — the server allows
            // only one active session at a time (ADR-0001), so a dangling
            // connection left open by a failed assertion here breaks every
            // *other* test in this class, not just this one. (Found live:
            // an assertion failure before `endSession()` left this test's
            // socket connected server-side, and the next test's `connect()`
            // then retried against a permanently "busy" slot until it
            // timed out.)
            client.close()
            job.cancel()
        }
    }
}
