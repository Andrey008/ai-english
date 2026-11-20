package com.aienglish.companion.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.IBinder
import android.support.v4.media.session.MediaSessionCompat
import android.support.v4.media.session.PlaybackStateCompat
import androidx.core.app.NotificationCompat
import androidx.media.session.MediaButtonReceiver
import com.aienglish.companion.AiEnglishApplication
import com.aienglish.companion.AppContainer
import com.aienglish.companion.MainActivity
import com.aienglish.companion.R
import com.aienglish.companion.data.ws.SessionPhase
import com.aienglish.companion.data.ws.WsEvent
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

private const val CHANNEL_ID = "voice_session"
private const val NOTIFICATION_ID = 1
private const val ACTION_END = "com.aienglish.companion.action.END_SESSION"
private const val EXTRA_CHARACTER_NAME = "character_name"

/** Keeps an active Voice Session's `WsSessionClient`/`AudioSessionController`
 * (both Application-scoped singletons, see `AiEnglishApplication`) alive
 * with the screen off or the app backgrounded, per `Docs/PRD.md` §7.2.
 * This service doesn't own the session's actual work — it only elevates
 * process priority via `startForeground()` and shows the notification
 * Android requires for that; the real WS/audio objects are the same ones
 * the UI uses, already Application-scoped for exactly this reason
 * (`STORY-05-08`'s prerequisite: `AppContainer` moved from an Activity-
 * local variable to `AiEnglishApplication`, since a `Service` has no way
 * to reach an Activity-owned instance). */
class VoiceSessionForegroundService : Service() {
    private lateinit var appContainer: AppContainer
    private lateinit var mediaSession: MediaSessionCompat
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var eventsJob: Job? = null
    private var muteObserverJob: Job? = null

    @Volatile private var characterName: String = "Character"
    @Volatile private var currentPhase: SessionPhase? = null
    @Volatile private var muted: Boolean = false

    override fun onCreate() {
        super.onCreate()
        appContainer = (application as AiEnglishApplication).appContainer
        createNotificationChannel()
        // STORY-05-09: a single TWS play/pause click maps to mute/unmute.
        // MediaSessionCompat is the standard modern path for Bluetooth
        // media-button routing — no manifest <receiver>/intent-filter
        // needed, the framework delivers hardware button events straight
        // to whichever session is currently active. The single-button
        // play<->pause toggle the earbuds expect is the OS's own behavior,
        // driven by the playback state this session reports (playbackState(),
        // kept current by the mutedFlow observer below).
        mediaSession = MediaSessionCompat(this, "VoiceSessionForegroundService").apply {
            setCallback(object : MediaSessionCompat.Callback() {
                override fun onPlay() = appContainer.audioSessionController.setMuted(false)
                override fun onPause() = appContainer.audioSessionController.setMuted(true)
            })
            setPlaybackState(playbackState(muted = false))
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        MediaButtonReceiver.handleIntent(mediaSession, intent)

        if (intent?.action == ACTION_END) {
            appContainer.wsSessionClient.endSession()
            appContainer.audioSessionController.stop()
            stopSelfCleanly()
            return START_NOT_STICKY
        }

        characterName = intent?.getStringExtra(EXTRA_CHARACTER_NAME) ?: characterName
        startForeground(
            NOTIFICATION_ID,
            buildNotification(),
            ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE or ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK,
        )
        mediaSession.isActive = true

        if (eventsJob == null) {
            eventsJob = scope.launch {
                appContainer.wsSessionClient.events.collect { event ->
                    when (event) {
                        is WsEvent.SessionState -> {
                            currentPhase = event.state
                            updateNotification()
                        }
                        is WsEvent.SessionEnded -> stopSelfCleanly()
                        else -> Unit
                    }
                }
            }
        }
        if (muteObserverJob == null) {
            // Reactive rather than called directly from the callbacks above —
            // this way the notification/media-session playback state stays
            // correct no matter which side (Bluetooth button or the in-app
            // mute button, STORY-05-07) changed mute.
            muteObserverJob = scope.launch {
                appContainer.audioSessionController.mutedFlow.collect { isMuted ->
                    muted = isMuted
                    mediaSession.setPlaybackState(playbackState(isMuted))
                    updateNotification()
                }
            }
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        eventsJob?.cancel()
        eventsJob = null
        muteObserverJob?.cancel()
        muteObserverJob = null
        mediaSession.release()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun stopSelfCleanly() {
        eventsJob?.cancel()
        eventsJob = null
        muteObserverJob?.cancel()
        muteObserverJob = null
        currentPhase = null
        mediaSession.isActive = false
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun playbackState(muted: Boolean): PlaybackStateCompat =
        PlaybackStateCompat.Builder()
            .setActions(PlaybackStateCompat.ACTION_PLAY or PlaybackStateCompat.ACTION_PAUSE or PlaybackStateCompat.ACTION_PLAY_PAUSE)
            .setState(
                if (muted) PlaybackStateCompat.STATE_PAUSED else PlaybackStateCompat.STATE_PLAYING,
                PlaybackStateCompat.PLAYBACK_POSITION_UNKNOWN,
                1f,
            )
            .build()

    private fun updateNotification() {
        val manager = getSystemService(NotificationManager::class.java)
        manager.notify(NOTIFICATION_ID, buildNotification())
    }

    private fun buildNotification(): Notification {
        val endIntent = Intent(this, VoiceSessionForegroundService::class.java).setAction(ACTION_END)
        val endPendingIntent = PendingIntent.getService(
            this, 0, endIntent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val openIntent = Intent(this, MainActivity::class.java)
        val contentPendingIntent = PendingIntent.getActivity(
            this, 0, openIntent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentTitle(characterName)
            .setContentText(if (muted) "Muted — ${phaseLabel(currentPhase)}" else phaseLabel(currentPhase))
            .setContentIntent(contentPendingIntent)
            .addAction(0, "End session", endPendingIntent)
            .setOngoing(true)
            .setSilent(true)
            .build()
    }

    private fun phaseLabel(phase: SessionPhase?): String = when (phase) {
        SessionPhase.PREPARING -> "Getting ready…"
        SessionPhase.LISTENING -> "Listening…"
        SessionPhase.PROCESSING -> "Thinking…"
        SessionPhase.SPEAKING -> "Speaking…"
        null -> "Connecting…"
    }

    private fun createNotificationChannel() {
        val channel = NotificationChannel(CHANNEL_ID, "Voice session", NotificationManager.IMPORTANCE_LOW)
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    companion object {
        fun startIntent(context: Context, characterName: String): Intent =
            Intent(context, VoiceSessionForegroundService::class.java)
                .putExtra(EXTRA_CHARACTER_NAME, characterName)
    }
}
