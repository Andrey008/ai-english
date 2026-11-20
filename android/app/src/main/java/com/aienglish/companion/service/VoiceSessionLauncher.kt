package com.aienglish.companion.service

import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat
import com.aienglish.companion.data.audio.AudioSessionController
import com.aienglish.companion.data.ws.LiveTranscript
import com.aienglish.companion.data.ws.TranscriptEntry
import com.aienglish.companion.data.ws.WsSessionClient
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** What a voice session starts with: a new conversation (character,
 * scenario, level, memory) or a past one to continue ([resumeSessionId],
 * ADR-0015; the server then restores character and scenario itself). */
data class SessionStartRequest(
    val characterName: String,
    val characterId: String? = null,
    val scenarioId: String? = null,
    val englishLevel: String? = null,
    val useMemory: Boolean = true,
    val resumeSessionId: String? = null,
    val pastTranscript: List<TranscriptEntry> = emptyList(),
    val useHeadsetMic: Boolean = true,
)

/** Starting and ending a session from any screen (the new-conversation
 * screen and a past conversation's Continue): socket, mic capture,
 * foreground service and the live transcript, together. */
class VoiceSessionLauncher(
    private val wsSessionClient: WsSessionClient,
    private val audioSessionController: AudioSessionController,
    private val liveTranscript: LiveTranscript,
) {
    private val _characterName = MutableStateFlow("Character")
    val characterName: StateFlow<String> = _characterName.asStateFlow()

    /** Returns false if the mic couldn't start (the session still runs:
     * the character talks but doesn't hear). */
    fun start(context: Context, request: SessionStartRequest): Boolean {
        liveTranscript.reset(request.pastTranscript)
        _characterName.value = request.characterName
        wsSessionClient.connect(
            characterId = request.characterId,
            scenarioId = request.scenarioId,
            englishLevel = request.englishLevel,
            useMemory = request.useMemory,
            resumeSessionId = request.resumeSessionId,
        )
        val captureStarted = audioSessionController.start(useHeadsetMic = request.useHeadsetMic)
        ContextCompat.startForegroundService(
            context,
            VoiceSessionForegroundService.startIntent(context, request.characterName),
        )
        return captureStarted
    }

    fun end(context: Context) {
        wsSessionClient.endSession()
        audioSessionController.stop()
        context.stopService(Intent(context, VoiceSessionForegroundService::class.java))
    }
}
