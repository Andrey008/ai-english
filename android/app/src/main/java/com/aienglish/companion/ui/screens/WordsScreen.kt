package com.aienglish.companion.ui.screens

import android.content.Intent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LargeTopAppBar
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.aienglish.companion.data.api.ApiResult
import com.aienglish.companion.data.api.VocabularyWord
import com.aienglish.companion.data.api.VocabularyWord.Companion.STATUS_ADDED
import com.aienglish.companion.data.api.VocabularyWord.Companion.STATUS_DISMISSED
import com.aienglish.companion.data.api.VocabularyWord.Companion.STATUS_NEW
import com.aienglish.companion.data.api.vocabularyClipboardText
import com.aienglish.companion.ui.LocalAppContainer
import kotlinx.coroutines.launch

private enum class WordsFilter(val label: String, val status: String) {
    NEW("To add", STATUS_NEW),
    ADDED("Added", STATUS_ADDED),
    HIDDEN("Hidden", STATUS_DISMISSED),
}

/** Words the user didn't understand in conversations (AE-5, `GET
 * /vocabulary`) — collected after each conversation from re-asks ("what
 * does X mean?") and bookmarks. The user copies them into EnglishDom by
 * hand, then marks them added. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WordsScreen() {
    val appContainer = LocalAppContainer.current
    val api = appContainer.apiClient
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val clipboard = LocalClipboardManager.current
    val snackbar = remember { SnackbarHostState() }
    var words by remember { mutableStateOf<List<VocabularyWord>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(false) }
    var filter by remember { mutableStateOf(WordsFilter.NEW) }

    suspend fun refresh() {
        loading = true
        error = null
        when (val result = api.listVocabulary()) {
            is ApiResult.Success -> words = result.data
            is ApiResult.HttpError -> error = "Server error ${result.code}" +
                if (result.code == 404) " — the server is older than this app, restart it." else ""
            is ApiResult.NetworkError -> error = "Can't reach the server — check Settings for the host/port."
        }
        loading = false
    }

    fun setStatus(ids: List<String>, status: String) {
        scope.launch {
            val result = if (ids.size == 1) api.setVocabularyStatus(ids.single(), status) else api.setVocabularyStatuses(ids, status)
            if (result is ApiResult.Success) {
                words = words?.map { if (it.id in ids) it.copy(status = status) else it }
            } else {
                snackbar.showSnackbar("Couldn't update — check the connection.")
            }
        }
    }

    fun delete(word: VocabularyWord) {
        scope.launch {
            if (api.deleteVocabulary(word.id) is ApiResult.Success) {
                words = words?.filterNot { it.id == word.id }
            } else {
                snackbar.showSnackbar("Couldn't delete — check the connection.")
            }
        }
    }

    LaunchedEffect(Unit) { refresh() }

    val all = words.orEmpty()
    val shown = all.filter { it.status == filter.status }
    val toAdd = all.filter { it.status == STATUS_NEW }

    // Copy (or share) everything still to add, then offer to mark it added
    // in one go — the usual flow is "copy, paste into EnglishDom, done".
    fun exported(how: String) {
        scope.launch {
            val result = snackbar.showSnackbar(
                "$how ${toAdd.size} word${if (toAdd.size == 1) "" else "s"}.",
                actionLabel = "Mark added",
                duration = SnackbarDuration.Long,
            )
            if (result == SnackbarResult.ActionPerformed) setStatus(toAdd.map { it.id }, STATUS_ADDED)
        }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            LargeTopAppBar(
                title = { Text("Words") },
                actions = {
                    IconButton(
                        onClick = {
                            clipboard.setText(AnnotatedString(vocabularyClipboardText(toAdd)))
                            exported("Copied")
                        },
                        enabled = toAdd.isNotEmpty(),
                    ) { Icon(Icons.Default.ContentCopy, contentDescription = "Copy words to add") }
                    IconButton(
                        onClick = {
                            val send = Intent(Intent.ACTION_SEND)
                                .setType("text/plain")
                                .putExtra(Intent.EXTRA_TEXT, vocabularyClipboardText(toAdd))
                            context.startActivity(Intent.createChooser(send, "Share words"))
                            exported("Shared")
                        },
                        enabled = toAdd.isNotEmpty(),
                    ) { Icon(Icons.Default.Share, contentDescription = "Share words to add") }
                    IconButton(onClick = { scope.launch { refresh() } }, enabled = !loading) {
                        Icon(Icons.Default.Refresh, contentDescription = "Refresh")
                    }
                },
            )
        },
    ) { padding ->
        when {
            words == null && error != null -> Column(
                Modifier.fillMaxSize().padding(padding).padding(24.dp),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(error.orEmpty(), textAlign = TextAlign.Center)
                Button(onClick = { scope.launch { refresh() } }, modifier = Modifier.padding(top = 16.dp)) { Text("Retry") }
            }
            words == null -> Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
            else -> Column(Modifier.fillMaxSize().padding(padding)) {
                SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
                    WordsFilter.entries.forEachIndexed { i, f ->
                        val count = all.count { it.status == f.status }
                        SegmentedButton(
                            selected = filter == f,
                            onClick = { filter = f },
                            shape = SegmentedButtonDefaults.itemShape(i, WordsFilter.entries.size),
                        ) { Text(if (count > 0) "${f.label} ($count)" else f.label) }
                    }
                }
                if (shown.isEmpty()) {
                    EmptyWords(filter, Modifier.weight(1f))
                } else {
                    LazyColumn(
                        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 24.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                        modifier = Modifier.weight(1f),
                    ) {
                        items(shown, key = { it.id }) { word ->
                            WordCard(
                                word = word,
                                onStatus = { setStatus(listOf(word.id), it) },
                                onDelete = { delete(word) },
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun WordCard(word: VocabularyWord, onStatus: (String) -> Unit, onDelete: () -> Unit) {
    var menuOpen by remember { mutableStateOf(false) }
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(start = 16.dp, top = 12.dp, bottom = 8.dp, end = 4.dp)) {
            Row(verticalAlignment = Alignment.Top) {
                Column(Modifier.weight(1f).padding(top = 4.dp)) {
                    Text(word.word, style = MaterialTheme.typography.titleLarge)
                    word.translationRu?.let {
                        Text(it, style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary)
                    }
                }
                Box {
                    IconButton(onClick = { menuOpen = true }) { Icon(Icons.Default.MoreVert, contentDescription = "More") }
                    DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                        if (word.status != STATUS_NEW) {
                            DropdownMenuItem(text = { Text("Back to “To add”") }, onClick = { menuOpen = false; onStatus(STATUS_NEW) })
                        }
                        if (word.status != STATUS_DISMISSED) {
                            DropdownMenuItem(text = { Text("Hide — I know it") }, onClick = { menuOpen = false; onStatus(STATUS_DISMISSED) })
                        }
                        DropdownMenuItem(text = { Text("Delete") }, onClick = { menuOpen = false; onDelete() })
                    }
                }
            }
            Column(Modifier.padding(end = 12.dp)) {
                word.explanation?.let {
                    Text(it, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 6.dp))
                }
                word.context?.let {
                    Text(
                        "“$it”",
                        style = MaterialTheme.typography.bodyMedium,
                        fontStyle = FontStyle.Italic,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(top = 6.dp),
                    )
                }
            }
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 4.dp, end = 8.dp)) {
                Text(
                    wordOrigin(word),
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.weight(1f),
                )
                if (word.status == STATUS_NEW) {
                    AssistChip(
                        onClick = { onStatus(STATUS_ADDED) },
                        label = { Text("Added") },
                        leadingIcon = { Icon(Icons.Default.Check, contentDescription = null) },
                    )
                } else {
                    TextButton(onClick = {}, enabled = false) { Text(if (word.status == STATUS_ADDED) "In EnglishDom" else "Hidden") }
                }
            }
        }
    }
}

/** "Asked · Emma · Weekend walk · 2×" — where the word came from. */
internal fun wordOrigin(word: VocabularyWord): String = listOfNotNull(
    if (word.source == "bookmark") "Bookmarked" else "Asked",
    word.characterName,
    word.sessionTitle,
    if (word.timesSeen > 1) "${word.timesSeen}×" else null,
).joinToString(" · ")

@Composable
private fun EmptyWords(filter: WordsFilter, modifier: Modifier) {
    Column(
        modifier.fillMaxWidth().padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            when (filter) {
                WordsFilter.NEW -> "No new words"
                WordsFilter.ADDED -> "Nothing marked as added yet"
                WordsFilter.HIDDEN -> "Nothing hidden"
            },
            style = MaterialTheme.typography.titleMedium,
        )
        if (filter == WordsFilter.NEW) {
            Text(
                "When you ask what a word means (“What does crisp mean?”) or tap “Unknown word” during a " +
                    "conversation, the word shows up here after the conversation ends — with a translation " +
                    "and the sentence you heard it in.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(top = 8.dp),
            )
        }
    }
}
