package com.aienglish.companion.ui.screens

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.aienglish.companion.data.api.ApiResult
import com.aienglish.companion.data.api.CharacterPreset
import com.aienglish.companion.ui.LocalAppContainer
import kotlinx.coroutines.launch

private sealed class ListUiState {
    data object Loading : ListUiState()
    data class Error(val message: String) : ListUiState()
    data class Loaded(val characters: List<CharacterPreset>) : ListUiState()
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CharacterListScreen(onCreateNew: () -> Unit, onEdit: (String) -> Unit) {
    val appContainer = LocalAppContainer.current
    val scope = rememberCoroutineScope()
    var uiState by remember { mutableStateOf<ListUiState>(ListUiState.Loading) }
    var pendingDelete by remember { mutableStateOf<CharacterPreset?>(null) }
    val selectedId by appContainer.characterSelectionStore.selectedIdFlow.collectAsState(initial = null)

    suspend fun refresh() {
        uiState = ListUiState.Loading
        uiState = when (val result = appContainer.apiClient.listCharacters()) {
            is ApiResult.Success -> ListUiState.Loaded(result.data)
            is ApiResult.HttpError -> ListUiState.Error("Server error ${result.code}")
            is ApiResult.NetworkError -> ListUiState.Error(
                "Can't reach server — check Settings for the correct host/port."
            )
        }
    }

    LaunchedEffect(Unit) { refresh() }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Characters") },
                actions = {
                    IconButton(onClick = { scope.launch { refresh() } }) {
                        Icon(Icons.Default.Refresh, contentDescription = "Refresh")
                    }
                },
            )
        },
        floatingActionButton = {
            FloatingActionButton(onClick = onCreateNew) {
                Icon(Icons.Default.Add, contentDescription = "Create character")
            }
        },
    ) { padding ->
        when (val state = uiState) {
            is ListUiState.Loading -> LoadingState(padding)
            is ListUiState.Error -> ErrorState(padding, state.message) { scope.launch { refresh() } }
            is ListUiState.Loaded -> {
                if (state.characters.isEmpty()) {
                    EmptyState(padding)
                } else {
                    LazyColumn(modifier = Modifier.fillMaxSize().padding(padding)) {
                        items(state.characters, key = { it.id }) { character ->
                            CharacterRow(
                                character = character,
                                isSelected = character.id == selectedId,
                                onSelect = { scope.launch { appContainer.characterSelectionStore.select(character.id) } },
                                onLongPress = { pendingDelete = character },
                                onEdit = { onEdit(character.id) },
                            )
                        }
                    }
                }
            }
        }
    }

    pendingDelete?.let { character ->
        AlertDialog(
            onDismissRequest = { pendingDelete = null },
            title = { Text("Delete ${character.name}?") },
            text = { Text("This removes the character from the server. This can't be undone.") },
            confirmButton = {
                TextButton(onClick = {
                    pendingDelete = null
                    scope.launch {
                        when (appContainer.apiClient.deleteCharacter(character.id)) {
                            is ApiResult.Success -> {
                                if (character.id == selectedId) appContainer.characterSelectionStore.clear()
                                refresh()
                            }
                            else -> refresh()
                        }
                    }
                }) { Text("Delete") }
            },
            dismissButton = {
                TextButton(onClick = { pendingDelete = null }) { Text("Cancel") }
            },
        )
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun CharacterRow(
    character: CharacterPreset,
    isSelected: Boolean,
    onSelect: () -> Unit,
    onLongPress: () -> Unit,
    onEdit: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .combinedClickable(onClick = onSelect, onLongClick = onLongPress)
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(48.dp)
                .background(MaterialTheme.colorScheme.primaryContainer, CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                character.name.take(1).uppercase(),
                color = MaterialTheme.colorScheme.onPrimaryContainer,
                style = MaterialTheme.typography.titleMedium,
            )
        }
        Column(modifier = Modifier.padding(start = 16.dp).weight(1f)) {
            Text(character.name, style = MaterialTheme.typography.titleMedium)
            Text(
                "${character.gender.name.lowercase()} · ${character.accent}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        if (isSelected) {
            Icon(
                Icons.Default.Check,
                contentDescription = "Selected",
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.padding(end = 4.dp),
            )
        }
        IconButton(onClick = onEdit) {
            Icon(Icons.Default.Edit, contentDescription = "Edit ${character.name}")
        }
    }
}

@Composable
private fun LoadingState(padding: PaddingValues) {
    Box(modifier = Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
        CircularProgressIndicator()
    }
}

@Composable
private fun EmptyState(padding: PaddingValues) {
    Column(
        modifier = Modifier.fillMaxSize().padding(padding).padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("No characters yet", style = MaterialTheme.typography.titleMedium)
        Text(
            "Tap + to create one.",
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center,
        )
    }
}

@Composable
private fun ErrorState(padding: PaddingValues, message: String, onRetry: () -> Unit) {
    Column(
        modifier = Modifier.fillMaxSize().padding(padding).padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(message, style = MaterialTheme.typography.bodyMedium, textAlign = TextAlign.Center)
        Button(onClick = onRetry, modifier = Modifier.padding(top = 16.dp)) { Text("Retry") }
    }
}
