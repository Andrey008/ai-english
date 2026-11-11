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
     * full stop/start cycle for a quick mute toggle. */
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
    fun start(headsetMic: Boolean = false, onChunk: (ByteArray) -> Unit): Boolean {
        if (!hasPermission) return false
        if (audioRecord != null) return true

        val minBufferSize = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        if (minBufferSize <= 0) return false

        val bufferSize = minBufferSize * 2
        // Headset mic: VOICE_COMMUNICATION is the source that follows the
        // communication device [HeadsetMicRouter] selected (Bluetooth SCO).
        // Otherwise VOICE_RECOGNITION: the source Android tunes for speech
        // recognisers, with minimal processing. VOICE_COMMUNICATION (used
        // before 2026-11-11) applies call-style noise suppression and AGC
        // tuned for human ears, which smears the consonants whisper needs.
        // Its echo cancellation isn't needed while turn-taking is
        // non-interruptible: the server drops mic audio while the reply
        // plays (`ws_session.py`). Revisit if EPIC-06 adds barge-in.
        val record = AudioRecord(
            if (headsetMic) MediaRecorder.AudioSource.VOICE_COMMUNICATION
            else MediaRecorder.AudioSource.VOICE_RECOGNITION,
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
