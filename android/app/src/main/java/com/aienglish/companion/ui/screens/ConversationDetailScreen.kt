package com.aienglish.companion.ui.screens

import android.widget.Toast
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.aienglish.companion.data.api.ApiResult
import com.aienglish.companion.data.api.ConversationDetail
import com.aienglish.companion.data.ws.TranscriptEntry
import com.aienglish.companion.service.SessionStartRequest
import com.aienglish.companion.ui.LocalAppContainer
import com.aienglish.companion.ui.components.Avatar
import com.aienglish.companion.ui.components.ChatTranscript
import kotlinx.coroutines.launch

/** A past conversation: its transcript, Continue (the character picks up
 * with the whole conversation in context, ADR-0015) and Delete. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ConversationDetailScreen(
    conversationId: String,
    onBack: () -> Unit,
    onContinued: () -> Unit,
) {
    val appContainer = LocalAppContainer.current
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val mic = rememberMicPermission()
    val sessionActive by appContainer.wsSessionClient.sessionActiveFlow.collectAsState()
    val forcePhoneMic by appContainer.audioPrefsStore.forcePhoneMicFlow.collectAsState(initial = false)
    var detail by remember { mutableStateOf<ConversationDetail?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var confirmDelete by remember { mutableStateOf(false) }

    LaunchedEffect(conversationId) {
        when (val result = appContainer.apiClient.getConversation(conversationId)) {
            is ApiResult.Success -> detail = result.data
            is ApiResult.HttpError -> error = if (result.code == 404) "This conversation no longer exists." else "Server error ${result.code}"
            is ApiResult.NetworkError -> error = "Can't reach the server — check Settings for the host/port."
        }
    }

    val transcript = detail?.transcript.orEmpty().map { turn ->
        if (turn.role == "user") TranscriptEntry.User(turn.text) else TranscriptEntry.Character(turn.text)
    }
    val characterName = detail?.characterName ?: "Character"

    fun continueConversation() {
        val conversation = detail ?: return
        val captureStarted = appContainer.voiceSessionLauncher.start(
            context,
            SessionStartRequest(
                characterName = characterName,
                resumeSessionId = conversation.id,
                pastTranscript = transcript,
                useHeadsetMic = !forcePhoneMic,
            ),
        )
        if (!captureStarted) {
            Toast.makeText(context, "Microphone unavailable — the character won't hear you.", Toast.LENGTH_LONG).show()
        }
        onContinued()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Avatar(characterName, size = 40.dp)
                        Column(modifier = Modifier.padding(start = 12.dp)) {
                            Text(
                                detail?.displayTitle ?: "Conversation",
                                style = MaterialTheme.typography.titleMedium,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                            detail?.let {
                                Text(
                                    "$characterName · ${formatWhen(it.startedAt)}",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                    }
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
                actions = {
                    if (detail != null && detail?.active != true) {
                        IconButton(onClick = { confirmDelete = true }) {
                            Icon(Icons.Default.Delete, contentDescription = "Delete conversation")
                        }
                    }
                },
            )
        },
        bottomBar = {
            val conversation = detail
            if (conversation != null) Surface(color = MaterialTheme.colorScheme.surfaceContainer) {
                Box(
                    modifier = Modifier.fillMaxWidth().navigationBarsPadding().padding(horizontal = 16.dp, vertical = 12.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    when {
                        !conversation.canResume -> Text(
                            "Its character was deleted, so it can't be continued.",
                            style = MaterialTheme.typography.bodyMedium,
                        )
                        sessionActive -> Text(
                            "End the current conversation to continue this one.",
                            style = MaterialTheme.typography.bodyMedium,
                        )
                        !mic.granted -> Button(onClick = mic.request, modifier = Modifier.fillMaxWidth().height(52.dp)) {
                            Text("Grant microphone access")
                        }
                        else -> Button(onClick = { continueConversation() }, modifier = Modifier.fillMaxWidth().height(52.dp)) {
                            Icon(Icons.Default.Mic, contentDescription = null)
                            Text("Continue conversation", modifier = Modifier.padding(start = 8.dp))
                        }
                    }
                }
            }
        },
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            val conversation = detail
            if (conversation == null) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    error?.let { Text(it, style = MaterialTheme.typography.bodyMedium) } ?: CircularProgressIndicator()
                }
                return@Column
            }
            ChatTranscript(
                transcript = transcript,
                characterName = characterName,
                characterKey = characterName,
                listState = rememberLazyListState(),
                modifier = Modifier.weight(1f),
            )
        }
    }

    if (confirmDelete) {
        AlertDialog(
            onDismissRequest = { confirmDelete = false },
            title = { Text("Delete this conversation?") },
            text = { Text("Its transcript is removed from the server. What the character remembers about you stays.") },
            confirmButton = {
                TextButton(onClick = {
                    confirmDelete = false
                    scope.launch {
                        val failure = when (val result = appContainer.apiClient.deleteConversation(conversationId)) {
                            is ApiResult.Success -> null
                            is ApiResult.HttpError -> "Couldn't delete (server error ${result.code})."
                            is ApiResult.NetworkError -> "Couldn't reach the server."
                        }
                        if (failure == null) onBack() else Toast.makeText(context, failure, Toast.LENGTH_LONG).show()
                    }
                }) { Text("Delete") }
            },
            dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text("Cancel") } },
        )
    }
}
