package com.aienglish.companion.data.audio

import android.util.Log
import com.aienglish.companion.data.ws.SessionPhase
import com.aienglish.companion.data.ws.WsEvent
import com.aienglish.companion.data.ws.WsSessionClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

private const val TAG = "AudioSessionController"

/** The only place mic/speaker mechanics meet the `/ws/session` wire
 * protocol — wires [AudioCapture]/[AudioPlayback] to a [WsSessionClient]'s
 * event stream. `STORY-05-07`'s screen owns creating/starting/stopping one
 * of these alongside the session itself; it doesn't need to touch
 * [AudioCapture]/[AudioPlayback] directly. */
class AudioSessionController(
    private val wsSessionClient: WsSessionClient,
    private val audioCapture: AudioCapture,
    private val audioPlayback: AudioPlayback,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var eventsJob: Job? = null

    @Volatile private var currentPhase: SessionPhase? = null

    // Observable (not just AudioCapture's plain @Volatile flag) so both the
    // Voice Session screen's mute button and STORY-05-09's Bluetooth TWS
    // media-button handler — which lives in the foreground service, a
    // different component entirely — can toggle mute and see each other's
    // changes reflected, whichever one the phone is next looked at from.
    private val _muted = MutableStateFlow(false)
    val mutedFlow: StateFlow<Boolean> = _muted.asStateFlow()

    // First real client-observed data point for FINDINGS.md open item #3
    // (network overhead — previously unmeasurable, no real client
    // existed). Logged, not yet aggregated/reported anywhere —
    // STORY-05-11 is where this gets consolidated into an actual number.
    @Volatile private var listeningEndedAtMs: Long? = null

    /** Returns `false` if mic capture couldn't start (missing permission
     * or unsupported device format) — playback still starts regardless,
     * since the character can still speak without a working mic even if
     * the user can't reply. */
    fun start(): Boolean {
        _muted.value = false
        audioPlayback.start()
        eventsJob = scope.launch {
            wsSessionClient.events.collect { event ->
                when (event) {
                    is WsEvent.SessionState -> {
                        currentPhase = event.state
                        if (event.state == SessionPhase.PROCESSING) {
                            listeningEndedAtMs = System.currentTimeMillis()
                        }
                    }
                    is WsEvent.AudioChunk -> {
                        listeningEndedAtMs?.let { startedAt ->
                            val elapsedMs = System.currentTimeMillis() - startedAt
                            Log.d(TAG, "client_observed_ttfa_ms=$elapsedMs")
                            listeningEndedAtMs = null
                        }
                        audioPlayback.write(event.pcm)
                    }
                    else -> Unit
                }
            }
        }
        return audioCapture.start { pcm ->
            // The server only turn-segments audio while it's actually
            // listening (`TurnSegmenter` in `ws_session.py`) — no
            // protocol harm in sending outside that window, but no point
            // either, and it avoids spending bandwidth on audio the
            // server will just discard.
            if (currentPhase == SessionPhase.LISTENING) {
                wsSessionClient.sendAudio(pcm)
            }
        }
    }

    fun setMuted(muted: Boolean) {
        audioCapture.muted = muted
        _muted.value = muted
    }

    fun toggleMute() {
        setMuted(!_muted.value)
    }

    fun stop() {
        eventsJob?.cancel()
        eventsJob = null
        audioCapture.stop()
        audioPlayback.stop()
    }
}
