package com.aienglish.companion.data.audio

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

private const val SAMPLE_RATE = 16_000

/** Raw PCM16/16kHz/mono mic capture (`ADR-0009` — `AudioRecord`, not
 * `MediaRecorder`, to match the wire protocol's raw framing directly).
 * No VAD/turn-segmentation here — that's server-side (`TurnSegmenter` in
 * `ws_session.py`); this just streams whatever the mic hears to
 * [onChunk] while running and unmuted.
 *
 * Requesting `RECORD_AUDIO` (the dialog, rationale UI) is deliberately
 * not this class's job — that needs an Activity and user-facing
 * explanation, which belongs in `STORY-05-07`'s screen. This class only
 * checks [hasPermission] and fails visibly ([start] returns `false`)
 * rather than crashing if it's missing. */
class AudioCapture(private val context: Context) {
    private var audioRecord: AudioRecord? = null
    private var job: Job? = null
    private val scope = CoroutineScope(Dispatchers.Default)

    @Volatile private var running = false

    /** Drops captured chunks without stopping the mic — cheaper than a
     * full stop/start cycle for a quick mute toggle, and keeps
     * `AudioRecord`'s echo-cancellation/AGC state warm. */
    @Volatile var muted: Boolean = false

    val hasPermission: Boolean
        get() = ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.RECORD_AUDIO,
        ) == PackageManager.PERMISSION_GRANTED

    /** Starts capture, invoking [onChunk] with raw PCM16 bytes as they
     * arrive. Returns `false` (does nothing else) if the permission
     * isn't granted or the device can't support this exact format —
     * both real, expected outcomes, not exceptional ones. Already
     * running is a no-op success. */
    fun start(onChunk: (ByteArray) -> Unit): Boolean {
        if (!hasPermission) return false
        if (audioRecord != null) return true

        val minBufferSize = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        if (minBufferSize <= 0) return false

        val bufferSize = minBufferSize * 2
        // VOICE_COMMUNICATION (not plain MIC) — this is a hands-free
        // conversational app with the device's own speaker active during
        // playback, so echo cancellation/noise suppression matter even
        // before EPIC-06's barge-in makes them essential.
        val record = AudioRecord(
            MediaRecorder.AudioSource.VOICE_COMMUNICATION,
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            bufferSize,
        )
        if (record.state != AudioRecord.STATE_INITIALIZED) {
            record.release()
            return false
        }

        audioRecord = record
        running = true
        record.startRecording()
        job = scope.launch {
            val buffer = ByteArray(bufferSize)
            while (running) {
                val read = record.read(buffer, 0, buffer.size)
                if (read > 0 && !muted) {
                    onChunk(buffer.copyOf(read))
                }
            }
        }
        return true
    }

    fun stop() {
        running = false
        audioRecord?.stop()
        audioRecord?.release()
        audioRecord = null
        job?.cancel()
        job = null
    }
}
