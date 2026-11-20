package com.aienglish.companion.ui.screens

import androidx.compose.animation.animateColorAsState
import kotlinx.coroutines.delay
import com.aienglish.companion.data.ws.PrepareInfo
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Bookmark
import androidx.compose.material.icons.filled.BookmarkAdd
import androidx.compose.material.icons.filled.CallEnd
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.MicOff
import androidx.compose.material.icons.filled.PlaylistAdd
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.FilledTonalIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.aienglish.companion.data.ws.SessionPhase
import com.aienglish.companion.data.ws.WsEvent
import com.aienglish.companion.ui.LocalAppContainer
import com.aienglish.companion.ui.components.Avatar
import com.aienglish.companion.ui.components.ChatActivity
import com.aienglish.companion.ui.components.ChatTranscript

/** The running conversation, full screen like a call (ADR-0015). Started
 * from the new-conversation screen or a past conversation's Continue
 * ([com.aienglish.companion.service.VoiceSessionLauncher]); [onClose]
 * goes back to the conversation list. Leaving with back keeps the
 * session running in the foreground service — the list then offers to
 * return here. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun VoiceSessionScreen(onClose: () -> Unit) {
    val appContainer = LocalAppContainer.current
    val context = LocalContext.current

    val characterName by appContainer.voiceSessionLauncher.characterName.collectAsState()
    val sessionActive by appContainer.wsSessionClient.sessionActiveFlow.collectAsState()
    val sessionPhase by appContainer.wsSessionClient.sessionPhaseFlow.collectAsState()
    val prepareInfo by appContainer.wsSessionClient.prepareInfoFlow.collectAsState()
    val transcript by appContainer.liveTranscript.entries.collectAsState()
    // Shared with STORY-05-09's Bluetooth TWS media-button handler (lives in
    // the foreground service) via AudioSessionController.mutedFlow, not
    // owned locally — either source toggling mute must show up here.
    val muted by appContainer.audioSessionController.mutedFlow.collectAsState()
    var errorMessage by remember { mutableStateOf<String?>(null) }
    // Bumped on each `bookmark_saved`; the button shows "saved" for a moment.
    var bookmarkAck by remember { mutableStateOf(0) }
    var addingWord by remember { mutableStateOf(false) }
    var notice by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(notice) {
        if (notice != null) {
            delay(2500)
            notice = null
        }
    }
    if (addingWord) {
        AddWordDialog(
            onDismiss = { addingWord = false },
            onAdded = { added ->
                addingWord = false
                notice = "“${added.word}” saved to Words"
            },
        )
    }

    LaunchedEffect(Unit) {
        appContainer.wsSessionClient.events.collect { event ->
            when (event) {
                is WsEvent.ServerError -> errorMessage = event.message
                is WsEvent.ConnectionLost -> errorMessage = "Connection lost — reconnecting…"
                is WsEvent.Reconnecting -> errorMessage = "Reconnecting (attempt ${event.attempt})…"
                is WsEvent.ReconnectFailed -> errorMessage = "Couldn't reconnect. Go back and continue the conversation again."
                is WsEvent.ConnectRefused -> errorMessage = event.message
                is WsEvent.SessionReady -> errorMessage = null
                is WsEvent.BookmarkSaved -> bookmarkAck++
                else -> Unit
            }
        }
    }

    // No teardown-on-dispose here, deliberately — found live while testing
    // STORY-05-10: leaving this screen disposes the composable just like
    // process death would, and ending the session on *any* disposal killed
    // it the moment the user looked elsewhere — defeating STORY-05-08's
    // foreground service. Ending a session is exclusively an explicit user
    // action (this screen's end button, or the notification's).

    Scaffold(
        topBar = {
            TopAppBar(
                navigationIcon = {
                    IconButton(onClick = onClose) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back to conversations")
                    }
                },
                actions = {
                    // Type a word in without interrupting the character (AE-5).
                    IconButton(onClick = { addingWord = true }) {
                        Icon(Icons.Default.PlaylistAdd, contentDescription = "Add a word to Words")
                    }
                },
                title = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Avatar(characterName, size = 40.dp)
                        Column(modifier = Modifier.padding(start = 12.dp)) {
                            Text(characterName, style = MaterialTheme.typography.titleMedium)
                            StatusLine(if (sessionActive) sessionPhase else null, sessionActive, muted)
                        }
                    }
                },
            )
        },
        bottomBar = {
            Surface(color = MaterialTheme.colorScheme.surfaceContainer) {
                Row(
                    modifier = Modifier.fillMaxWidth().navigationBarsPadding().padding(vertical = 16.dp),
                    horizontalArrangement = Arrangement.spacedBy(32.dp, Alignment.CenterHorizontally),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    if (sessionActive) {
                        MicButton(muted, listening = sessionPhase == SessionPhase.LISTENING) {
                            appContainer.audioSessionController.toggleMute()
                        }
                        BookmarkButton(bookmarkAck) {
                            if (!appContainer.wsSessionClient.sendBookmark()) {
                                errorMessage = "Not connected — the bookmark wasn't saved."
                            }
                        }
                        FilledIconButton(
                            onClick = {
                                appContainer.voiceSessionLauncher.end(context)
                                onClose()
                            },
                            modifier = Modifier.size(64.dp),
                            colors = IconButtonDefaults.filledIconButtonColors(
                                containerColor = Color(0xFFE53935),
                                contentColor = Color.White,
                            ),
                        ) { Icon(Icons.Default.CallEnd, contentDescription = "End conversation", modifier = Modifier.size(30.dp)) }
                    } else {
                        Button(onClick = onClose) { Text("Back to conversations") }
                    }
                }
            }
        },
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            errorMessage?.let { message ->
                Surface(
                    color = MaterialTheme.colorScheme.errorContainer,
                    contentColor = MaterialTheme.colorScheme.onErrorContainer,
                    shape = MaterialTheme.shapes.medium,
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
                ) {
                    Row(modifier = Modifier.padding(start = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(message, modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
                        TextButton(onClick = { errorMessage = null }) { Text("Dismiss") }
                    }
                }
            }

            notice?.let { message ->
                Surface(
                    color = MaterialTheme.colorScheme.secondaryContainer,
                    contentColor = MaterialTheme.colorScheme.onSecondaryContainer,
                    shape = MaterialTheme.shapes.medium,
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
                ) {
                    Text(message, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(16.dp))
                }
            }

            val preparing = prepareInfo
            if (sessionActive && sessionPhase == SessionPhase.PREPARING && preparing != null) {
                PreparingPanel(characterName, preparing, Modifier.weight(1f))
            } else if (transcript.isEmpty() && sessionPhase != SessionPhase.PROCESSING) {
                EmptyCallHint(characterName, sessionActive, sessionPhase, Modifier.weight(1f))
            } else {
                ChatTranscript(
                    transcript = transcript,
                    characterName = characterName,
                    characterKey = characterName,
                    listState = rememberLazyListState(),
                    activity = if (sessionActive && sessionPhase == SessionPhase.PROCESSING) ChatActivity.THINKING else ChatActivity.NONE,
                    modifier = Modifier.weight(1f),
                )
            }
        }
    }
}

/** "Listening…" with a pulsing dot, "Thinking…", "Speaking…". */
@Composable
private fun StatusLine(phase: SessionPhase?, active: Boolean, muted: Boolean) {
    val (label, color) = when {
        !active -> "Conversation ended" to MaterialTheme.colorScheme.onSurfaceVariant
        muted && phase == SessionPhase.LISTENING -> "Muted" to MaterialTheme.colorScheme.error
        phase == SessionPhase.PREPARING -> "Getting ready…" to MaterialTheme.colorScheme.onSurfaceVariant
        phase == SessionPhase.LISTENING -> "Listening — your turn" to Color(0xFF2E9D5B)
        phase == SessionPhase.PROCESSING -> "Thinking…" to MaterialTheme.colorScheme.tertiary
        phase == SessionPhase.SPEAKING -> "Speaking…" to MaterialTheme.colorScheme.primary
        else -> "Connecting…" to MaterialTheme.colorScheme.onSurfaceVariant
    }
    val pulse = rememberInfiniteTransition(label = "status")
    val alpha by pulse.animateFloat(0.3f, 1f, infiniteRepeatable(tween(700), RepeatMode.Reverse), label = "alpha")
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(
            Modifier.size(8.dp)
                .background(color.copy(alpha = if (active && phase != null) alpha else 1f), CircleShape),
        )
        Text(label, style = MaterialTheme.typography.bodySmall, color = color, modifier = Modifier.padding(start = 6.dp))
    }
}

/** "I didn't get a word here" (AE-5): marks the line being spoken (or just
 * spoken); after the conversation its hard words land on the Words tab.
 * [ack] changes each time the server confirms — the icon then fills for
 * a moment. */
@Composable
private fun BookmarkButton(ack: Int, onClick: () -> Unit) {
    val haptics = LocalHapticFeedback.current
    var saved by remember { mutableStateOf(false) }
    LaunchedEffect(ack) {
        if (ack == 0) return@LaunchedEffect
        saved = true
        haptics.performHapticFeedback(HapticFeedbackType.LongPress)
        delay(1500)
        saved = false
    }
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        FilledTonalIconButton(onClick = onClick, modifier = Modifier.size(56.dp)) {
            Icon(
                if (saved) Icons.Default.Bookmark else Icons.Default.BookmarkAdd,
                contentDescription = "Didn't get a word — save it for later",
                modifier = Modifier.size(26.dp),
            )
        }
        Text(
            if (saved) "Saved" else "Unknown word",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 4.dp),
        )
    }
}

/** The mic button gently pulses while it's the user's turn. */
@Composable
private fun MicButton(muted: Boolean, listening: Boolean, onClick: () -> Unit) {
    val pulse = rememberInfiniteTransition(label = "mic")
    val scale by pulse.animateFloat(1f, 1.08f, infiniteRepeatable(tween(900), RepeatMode.Reverse), label = "scale")
    val container by animateColorAsState(
        if (muted) MaterialTheme.colorScheme.surfaceContainerHighest else MaterialTheme.colorScheme.primaryContainer,
        label = "micColor",
    )
    FilledIconButton(
        onClick = onClick,
        modifier = Modifier.size(64.dp).scale(if (listening && !muted) scale else 1f),
        colors = IconButtonDefaults.filledIconButtonColors(
            containerColor = container,
            contentColor = if (muted) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onPrimaryContainer,
        ),
    ) {
        Icon(
            if (muted) Icons.Default.MicOff else Icons.Default.Mic,
            contentDescription = if (muted) "Unmute" else "Mute",
            modifier = Modifier.size(30.dp),
        )
    }
}

@Composable
private fun EmptyCallHint(name: String, active: Boolean, phase: SessionPhase?, modifier: Modifier) {
    Column(
        modifier = modifier.fillMaxWidth().padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Avatar(name, size = 96.dp)
        Text(name, style = MaterialTheme.typography.headlineSmall, modifier = Modifier.padding(top = 16.dp))
        Text(
            when {
                !active -> "Conversation ended"
                phase == null -> "Connecting…"
                else -> "Say hello — $name is listening."
            },
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 8.dp),
        )
    }
}

/** Fill for the "getting ready" bar: the server only gives an estimate,
 * so the bar reaches 90% at [expectedS] and then creeps toward 99% until
 * the session actually opens (the panel then disappears). */
internal fun prepareProgress(elapsedS: Double, expectedS: Double): Float {
    val expected = expectedS.coerceAtLeast(1.0)
    return if (elapsedS < expected) {
        (0.9 * elapsedS / expected).toFloat()
    } else {
        (0.9 + 0.09 * (1 - kotlin.math.exp(-(elapsedS - expected) / expected))).toFloat()
    }
}

/** Session start while the server warms the model up: avatar, a progress
 * bar with a percentage, and what is happening. The mic opens after. */
@Composable
private fun PreparingPanel(name: String, info: PrepareInfo, modifier: Modifier) {
    var progress by remember(info) { mutableFloatStateOf(0f) }
    LaunchedEffect(info) {
        while (true) {
            val elapsedS = (System.currentTimeMillis() - info.startedAtMs) / 1000.0
            progress = prepareProgress(elapsedS, info.expectedS)
            delay(100)
        }
    }
    val shown by animateFloatAsState(progress, label = "prepare")
    Column(
        modifier = modifier.fillMaxWidth().padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Avatar(name, size = 96.dp)
        Text(
            "$name is getting ready…",
            style = MaterialTheme.typography.headlineSmall,
            modifier = Modifier.padding(top = 16.dp),
        )
        LinearProgressIndicator(
            progress = { shown },
            modifier = Modifier.fillMaxWidth().padding(top = 24.dp),
        )
        Text(
            "${(shown * 100).toInt()}%",
            style = MaterialTheme.typography.titleMedium,
            modifier = Modifier.padding(top = 8.dp),
        )
        Text(
            if (info.modelLoading) "Loading the model into memory — the first conversation after a break takes a few seconds longer."
            else "Reading the character and your conversation.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 8.dp),
        )
    }
}
