package com.aienglish.companion.ui.screens

import android.widget.Toast
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Call
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.LargeTopAppBar
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.aienglish.companion.data.api.ApiResult
import com.aienglish.companion.data.api.ConversationSummary
import com.aienglish.companion.ui.LocalAppContainer
import com.aienglish.companion.ui.components.Avatar
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

private const val WRAP_UP_REFRESH_MS = 8_000L

/** The app's home (ADR-0015): past conversations, newest first, and a
 * New conversation button. A conversation still running (the session
 * lives in the foreground service) shows a banner to go back to it. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ConversationListScreen(
    onNew: () -> Unit,
    onOpen: (String) -> Unit,
    onOpenActive: () -> Unit,
) {
    val appContainer = LocalAppContainer.current
    val scope = rememberCoroutineScope()
    val sessionActive by appContainer.wsSessionClient.sessionActiveFlow.collectAsState()
    val characterName by appContainer.voiceSessionLauncher.characterName.collectAsState()
    var conversations by remember { mutableStateOf<List<ConversationSummary>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    val context = LocalContext.current
    var renaming by remember { mutableStateOf<ConversationSummary?>(null) }
    var deleting by remember { mutableStateOf<ConversationSummary?>(null) }

    fun showFailure(result: ApiResult<*>, action: String) {
        val message = when (result) {
            is ApiResult.HttpError -> "Couldn't $action (server error ${result.code})."
            is ApiResult.NetworkError -> "Couldn't reach the server."
            is ApiResult.Success -> return
        }
        Toast.makeText(context, message, Toast.LENGTH_LONG).show()
    }

    suspend fun refresh() {
        error = null
        when (val result = appContainer.apiClient.listConversations()) {
            is ApiResult.Success -> conversations = result.data
            is ApiResult.HttpError -> error = "Server error ${result.code}"
            is ApiResult.NetworkError -> error = "Can't reach the server — check Settings for the host/port."
        }
    }

    // Also re-runs when a session ends; the server writes that
    // conversation's title a few seconds later, hence the second pass.
    // The app opening: load the model while the user picks what to do.
    LaunchedEffect(Unit) { appContainer.apiClient.warmup() }

    LaunchedEffect(sessionActive) {
        refresh()
        if (!sessionActive) {
            delay(WRAP_UP_REFRESH_MS)
            refresh()
        }
    }

    Scaffold(
        topBar = {
            LargeTopAppBar(
                title = { Text("Conversations") },
                actions = {
                    IconButton(onClick = { scope.launch { refresh() } }) {
                        Icon(Icons.Default.Refresh, contentDescription = "Refresh")
                    }
                },
            )
        },
        floatingActionButton = {
            if (!sessionActive) {
                ExtendedFloatingActionButton(
                    onClick = onNew,
                    icon = { Icon(Icons.Default.Add, contentDescription = null) },
                    text = { Text("New conversation") },
                )
            }
        },
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            if (sessionActive) {
                Card(
                    onClick = onOpenActive,
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer),
                ) {
                    Row(modifier = Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                        Avatar(characterName, size = 40.dp)
                        Column(modifier = Modifier.weight(1f).padding(start = 12.dp)) {
                            Text("Talking with $characterName", style = MaterialTheme.typography.titleSmall)
                            Text("Tap to return to the call", style = MaterialTheme.typography.bodySmall)
                        }
                        Icon(Icons.Default.Call, contentDescription = null)
                    }
                }
            }

            val list = conversations
            when {
                error != null && list == null -> CenteredMessage(error!!) {
                    Button(onClick = { scope.launch { refresh() } }, modifier = Modifier.padding(top = 16.dp)) {
                        Text("Retry")
                    }
                }
                list == null -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator()
                }
                list.isEmpty() -> CenteredMessage("No conversations yet.\nTap New conversation to start talking.", icon = true)
                else -> LazyColumn(modifier = Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 96.dp)) {
                    items(list, key = { it.id }) { conversation ->
                        ConversationRow(
                            conversation,
                            onClick = { if (conversation.active) onOpenActive() else onOpen(conversation.id) },
                            onRename = { renaming = conversation },
                            onDelete = { deleting = conversation },
                        )
                        HorizontalDivider(modifier = Modifier.padding(start = 78.dp), color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f))
                    }
                }
            }
        }
    }

    renaming?.let { conversation ->
        RenameDialog(
            initial = conversation.displayTitle,
            onDismiss = { renaming = null },
            onSave = { title ->
                renaming = null
                scope.launch {
                    val result = appContainer.apiClient.renameConversation(conversation.id, title)
                    showFailure(result, "rename")
                    refresh()
                }
            },
        )
    }

    deleting?.let { conversation ->
        AlertDialog(
            onDismissRequest = { deleting = null },
            title = { Text("Delete \"${conversation.displayTitle}\"?") },
            text = { Text("Its transcript is removed from the server. What the character remembers about you stays.") },
            confirmButton = {
                TextButton(onClick = {
                    deleting = null
                    scope.launch {
                        showFailure(appContainer.apiClient.deleteConversation(conversation.id), "delete")
                        refresh()
                    }
                }) { Text("Delete") }
            },
            dismissButton = { TextButton(onClick = { deleting = null }) { Text("Cancel") } },
        )
    }
}

@Composable
private fun RenameDialog(initial: String, onDismiss: () -> Unit, onSave: (String) -> Unit) {
    var title by remember { mutableStateOf(initial) }
    val valid = title.isNotBlank() && title.length <= 120
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Rename conversation") },
        text = {
            OutlinedTextField(value = title, onValueChange = { title = it }, singleLine = true, isError = !valid)
        },
        confirmButton = { TextButton(onClick = { onSave(title.trim()) }, enabled = valid) { Text("Save") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

/** Tap opens it; a long press offers Rename and Delete (not for the
 * conversation that is running right now). */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ConversationRow(
    conversation: ConversationSummary,
    onClick: () -> Unit,
    onRename: () -> Unit,
    onDelete: () -> Unit,
) {
    var menuOpen by remember { mutableStateOf(false) }
    Box {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .combinedClickable(onClick = onClick, onLongClick = { menuOpen = true })
                .padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Avatar(conversation.characterName, size = 48.dp)
            Column(modifier = Modifier.weight(1f).padding(start = 14.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        conversation.displayTitle,
                        style = MaterialTheme.typography.titleMedium,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f),
                    )
                    Text(
                        formatWhen(conversation.lastTurnAt ?: conversation.startedAt),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(start = 8.dp),
                    )
                }
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 2.dp)) {
                    Text(
                        "${conversation.characterName ?: "Deleted character"} · ${conversation.userTurns} " +
                            if (conversation.userTurns == 1) "reply" else "replies",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f),
                    )
                    if (conversation.active) {
                        Surface(
                            color = MaterialTheme.colorScheme.secondaryContainer,
                            contentColor = MaterialTheme.colorScheme.onSecondaryContainer,
                            shape = CircleShape,
                        ) {
                            Text("Live", style = MaterialTheme.typography.labelSmall, modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp))
                        }
                    }
                }
            }
        }
        DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
            DropdownMenuItem(
                text = { Text("Rename") },
                leadingIcon = { Icon(Icons.Default.Edit, contentDescription = null) },
                onClick = { menuOpen = false; onRename() },
            )
            DropdownMenuItem(
                text = { Text("Delete") },
                leadingIcon = { Icon(Icons.Default.Delete, contentDescription = null) },
                enabled = !conversation.active,
                onClick = { menuOpen = false; onDelete() },
            )
        }
    }
}

@Composable
private fun CenteredMessage(message: String, icon: Boolean = false, action: @Composable () -> Unit = {}) {
    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        if (icon) {
            Icon(
                Icons.AutoMirrored.Filled.Chat,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(64.dp).padding(bottom = 12.dp),
            )
        }
        Text(message, style = MaterialTheme.typography.bodyMedium, textAlign = TextAlign.Center)
        action()
    }
}

private val timeFormat = DateTimeFormatter.ofPattern("HH:mm")
private val dateFormat = DateTimeFormatter.ofPattern("d MMM")

/** "14:05" for today, "Yesterday", or "3 Nov" — server times are UTC ISO. */
fun formatWhen(iso: String): String {
    val local = runCatching { OffsetDateTime.parse(iso).atZoneSameInstant(ZoneId.systemDefault()) }
        .getOrNull() ?: return ""
    val today = LocalDate.now()
    return when (local.toLocalDate()) {
        today -> local.format(timeFormat)
        today.minusDays(1) -> "Yesterday"
        else -> local.format(dateFormat)
    }
}
