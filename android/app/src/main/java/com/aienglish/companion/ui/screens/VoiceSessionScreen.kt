package com.aienglish.companion.ui.screens

import android.Manifest
import android.content.Intent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.MicOff
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.aienglish.companion.data.api.ApiResult
import com.aienglish.companion.data.api.ScenarioDefinition
import com.aienglish.companion.data.ws.SessionPhase
import com.aienglish.companion.data.ws.WsEvent
import com.aienglish.companion.service.VoiceSessionForegroundService
import com.aienglish.companion.ui.LocalAppContainer

private sealed class TranscriptEntry {
    data class User(val text: String) : TranscriptEntry()
    data class Character(val text: String) : TranscriptEntry()
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun VoiceSessionScreen() {
    val appContainer = LocalAppContainer.current
    val context = LocalContext.current

    val selectedCharacterId by appContainer.characterSelectionStore.selectedIdFlow.collectAsState(initial = null)
    var characterName by remember { mutableStateOf("Character") }

    var scenarios by remember { mutableStateOf<List<ScenarioDefinition>>(emptyList()) }
    var selectedScenarioId by remember { mutableStateOf<String?>(null) }

    var micGranted by remember { mutableStateOf(appContainer.audioCapture.hasPermission) }
    // Requested together with RECORD_AUDIO, but only the mic gates
    // starting a session — a denied notification permission just means
    // the foreground-service notification (STORY-05-08) won't be
    // visible while backgrounded; the session still works.
    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) { granted -> micGranted = granted[Manifest.permission.RECORD_AUDIO] == true }

    LaunchedEffect(selectedCharacterId) {
        val id = selectedCharacterId ?: return@LaunchedEffect
        when (val result = appContainer.apiClient.getCharacter(id)) {
            is ApiResult.Success -> characterName = result.data.name
            else -> Unit
        }
    }

    // A permission granted externally (Settings, or adb) never fires the
    // launcher callback above — found live testing this story: `pm grant`
    // from outside the app left this screen stuck showing the blocked
    // state even though the OS permission was already granted. Re-check
    // on every resume, so "grant it in Settings, come back" works without
    // an app restart, matching this story's own acceptance criterion.
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                micGranted = appContainer.audioCapture.hasPermission
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    // Seeded from the client's own current state, not hardcoded false/null —
    // this composable is recreated on every tab switch back to this screen,
    // and a session started before the switch is very much still running
    // (that's the whole point of STORY-05-08's foreground service); without
    // this the screen would wrongly show the pre-session Start button for
    // an already-active session until the next server event happened to
    // arrive.
    var sessionActive by remember { mutableStateOf(appContainer.wsSessionClient.sessionActiveFlow.value) }
    var sessionPhase by remember { mutableStateOf(appContainer.wsSessionClient.sessionPhaseFlow.value) }
    var transcript by remember { mutableStateOf<List<TranscriptEntry>>(emptyList()) }
    // Shared with STORY-05-09's Bluetooth TWS media-button handler (lives in
    // the foreground service) via AudioSessionController.mutedFlow, not
    // owned locally — either source toggling mute must show up here.
    val muted by appContainer.audioSessionController.mutedFlow.collectAsState()
    var errorMessage by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) {
        when (val result = appContainer.apiClient.listScenarios()) {
            is ApiResult.Success -> scenarios = result.data
            else -> Unit // freeform still works without scenario content
        }
    }

    // Subscribed for the screen's whole lifetime (not gated on
    // sessionActive) — WsSessionClient's SharedFlow has no replay, so a
    // collector started only after connect() risks missing the first
    // session_ready/opening-line events.
    LaunchedEffect(Unit) {
        appContainer.wsSessionClient.events.collect { event ->
            when (event) {
                is WsEvent.SessionState -> sessionPhase = event.state
                is WsEvent.TranscriptFinal -> transcript = transcript + TranscriptEntry.User(event.text)
                is WsEvent.ResponseTextChunk -> transcript = transcript + TranscriptEntry.Character(event.text)
                is WsEvent.ServerError -> errorMessage = event.message
                is WsEvent.SessionEnded -> {
                    sessionActive = false
                    sessionPhase = null
                }
                is WsEvent.ConnectionLost -> errorMessage = "Connection lost — reconnecting…"
                is WsEvent.Reconnecting -> errorMessage = "Reconnecting (attempt ${event.attempt})…"
                is WsEvent.ReconnectFailed -> errorMessage = "Couldn't reconnect. End and start a new session."
                else -> Unit
            }
        }
    }

    // No teardown-on-dispose here, deliberately — found live while testing
    // STORY-05-10: switching bottom-nav tabs away from this screen disposes
    // the composable just like process death would, and this used to call
    // endSession()/stop() on *any* disposal, silently killing every active
    // session the moment the user checked Settings or Characters mid-session
    // — completely defeating STORY-05-08's foreground service, whose whole
    // point is to keep the session alive independent of this screen's own
    // lifecycle. Ending a session is now exclusively an explicit user action
    // (this screen's "End session" button, or the notification's).

    fun startSession() {
        transcript = emptyList()
        errorMessage = null
        sessionPhase = null
        sessionActive = true
        appContainer.wsSessionClient.connect(
            characterId = selectedCharacterId,
            scenarioId = selectedScenarioId,
        )
        val captureStarted = appContainer.audioSessionController.start()
        if (!captureStarted) {
            errorMessage = "Microphone unavailable — the character can still talk, but won't hear you."
        }
        ContextCompat.startForegroundService(
            context,
            VoiceSessionForegroundService.startIntent(context, characterName),
        )
    }

    fun endSession() {
        appContainer.wsSessionClient.endSession()
        appContainer.audioSessionController.stop()
        context.stopService(Intent(context, VoiceSessionForegroundService::class.java))
        sessionActive = false
        sessionPhase = null
    }

    fun toggleMute() {
        appContainer.audioSessionController.toggleMute()
    }

    Scaffold(topBar = { TopAppBar(title = { Text("Voice session") }) }) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            errorMessage?.let { message ->
                Card(modifier = Modifier.fillMaxWidth().padding(16.dp)) {
                    Row(
                        modifier = Modifier.padding(12.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(message, modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
                        TextButton(onClick = { errorMessage = null }) { Text("Dismiss") }
                    }
                }
            }

            if (!sessionActive) {
                PreSessionContent(
                    characterSelected = selectedCharacterId != null,
                    scenarios = scenarios,
                    selectedScenarioId = selectedScenarioId,
                    onSelectScenario = { selectedScenarioId = it },
                    micGranted = micGranted,
                    onRequestMic = {
                        permissionLauncher.launch(
                            arrayOf(Manifest.permission.RECORD_AUDIO, Manifest.permission.POST_NOTIFICATIONS),
                        )
                    },
                    onStart = { startSession() },
                )
            } else {
                InSessionContent(
                    phase = sessionPhase,
                    transcript = transcript,
                    muted = muted,
                    onToggleMute = { toggleMute() },
                    onEnd = { endSession() },
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PreSessionContent(
    characterSelected: Boolean,
    scenarios: List<ScenarioDefinition>,
    selectedScenarioId: String?,
    onSelectScenario: (String?) -> Unit,
    micGranted: Boolean,
    onRequestMic: () -> Unit,
    onStart: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("Hands-Free Room", style = MaterialTheme.typography.headlineSmall)

        if (!characterSelected) {
            Text(
                "Select a character on the Characters tab first.",
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.padding(top = 12.dp),
            )
            return@Column
        }

        if (!micGranted) {
            Text(
                "Microphone access is needed to talk to your character.",
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.padding(top = 12.dp, bottom = 8.dp),
            )
            Button(onClick = onRequestMic) { Text("Grant microphone access") }
            return@Column
        }

        Text(
            "Scenario",
            style = MaterialTheme.typography.labelLarge,
            modifier = Modifier.padding(top = 24.dp, bottom = 8.dp),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(
                selected = selectedScenarioId == null,
                onClick = { onSelectScenario(null) },
                label = { Text("Freeform") },
            )
        }
        scenarios.forEach { scenario ->
            FilterChip(
                selected = selectedScenarioId == scenario.id,
                onClick = { onSelectScenario(scenario.id) },
                label = { Text(scenario.title) },
                modifier = Modifier.padding(top = 8.dp),
            )
        }

        Button(onClick = onStart, modifier = Modifier.padding(top = 24.dp)) {
            Text("Start")
        }
    }
}

@Composable
private fun InSessionContent(
    phase: SessionPhase?,
    transcript: List<TranscriptEntry>,
    muted: Boolean,
    onToggleMute: () -> Unit,
    onEnd: () -> Unit,
) {
    val listState = rememberLazyListState()
    LaunchedEffect(transcript.size) {
        if (transcript.isNotEmpty()) listState.animateScrollToItem(transcript.size - 1)
    }

    Column(modifier = Modifier.fillMaxSize()) {
        Text(
            phaseLabel(phase),
            style = MaterialTheme.typography.titleMedium,
            modifier = Modifier.fillMaxWidth().padding(16.dp),
        )

        LazyColumn(
            state = listState,
            modifier = Modifier.weight(1f).fillMaxWidth().padding(horizontal = 16.dp),
        ) {
            items(transcript) { entry ->
                val (speaker, text) = when (entry) {
                    is TranscriptEntry.User -> "You" to entry.text
                    is TranscriptEntry.Character -> "Character" to entry.text
                }
                Column(modifier = Modifier.padding(vertical = 6.dp)) {
                    Text(speaker, style = MaterialTheme.typography.labelSmall)
                    Text(text, style = MaterialTheme.typography.bodyLarge)
                }
            }
        }

        Row(
            modifier = Modifier.fillMaxWidth().padding(24.dp),
            horizontalArrangement = Arrangement.SpaceEvenly,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onToggleMute) {
                Icon(
                    if (muted) Icons.Default.MicOff else Icons.Default.Mic,
                    contentDescription = if (muted) "Unmute" else "Mute",
                )
            }
            Button(onClick = onEnd) { Text("End session") }
        }
    }
}

private fun phaseLabel(phase: SessionPhase?): String = when (phase) {
    SessionPhase.LISTENING -> "Listening…"
    SessionPhase.PROCESSING -> "Thinking…"
    SessionPhase.SPEAKING -> "Speaking…"
    null -> "Connecting…"
}
