package com.aienglish.companion.data.audio

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioTrack
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

private const val SAMPLE_RATE = 16_000

// 10ms of PCM16 mono silence — small, so speech arriving mid-gap waits at
// most this long (plus the track buffer) behind it.
private val SILENCE_CHUNK = ByteArray(SAMPLE_RATE / 100 * 2)

/** Streaming PCM16/16kHz/mono playback (`ADR-0009` — `AudioTrack`, not
 * ExoPlayer) for TTS audio arriving over the WS protocol. One `AudioTrack`
 * spans the whole session, not one per sentence — the protocol never
 * overlaps sentences (`ws_session.py`'s `_speak_sentence` sends one fully
 * before the next state transition), so sentences just stream through
 * back-to-back; recreating the track per sentence would only add clicks/
 * gaps between them for no benefit.
 *
 * A writer thread feeds the track continuously, padding with silence
 * whenever no TTS audio is queued. Found on real hardware
 * (`STORY-05-11`): letting the track run dry between replies let the
 * output thread drop to standby after 3s, and every reply then restarted
 * the stream — over Bluetooth A2DP (+ Dolby processing on the Motorola)
 * that start is faded in, so each reply audibly ramped up from silence. */
class AudioPlayback(private val context: Context) {
    private var audioTrack: AudioTrack? = null
    private var focusRequest: AudioFocusRequest? = null
    private var writerThread: Thread? = null
    private val queue = LinkedBlockingQueue<ByteArray>()
    @Volatile private var running = false

    private val audioManager: AudioManager
        get() = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager

    fun start() {
        if (audioTrack != null) return

        val attributes = AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
            .build()

        val request = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
            .setAudioAttributes(attributes)
            .build()
        audioManager.requestAudioFocus(request)
        focusRequest = request

        val minBufferSize = AudioTrack.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_OUT_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        val track = AudioTrack(
            attributes,
            AudioFormat.Builder()
                .setSampleRate(SAMPLE_RATE)
                .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                .build(),
            minBufferSize * 2,
            AudioTrack.MODE_STREAM,
            AudioManager.AUDIO_SESSION_ID_GENERATE,
        )
        track.play()
        audioTrack = track

        queue.clear()
        running = true
        writerThread = Thread({
            while (running) {
                // Blocking write paces this loop at real time.
                val pcm = queue.poll(5, TimeUnit.MILLISECONDS) ?: SILENCE_CHUNK
                track.write(pcm, 0, pcm.size)
            }
        }, "AudioPlaybackWriter").apply { start() }
    }

    fun write(pcm: ByteArray) {
        if (running) queue.offer(pcm)
    }

    fun stop() {
        running = false
        writerThread?.join(500)
        writerThread = null
        queue.clear()
        audioTrack?.stop()
        audioTrack?.release()
        audioTrack = null
        focusRequest?.let { audioManager.abandonAudioFocusRequest(it) }
        focusRequest = null
    }
}
