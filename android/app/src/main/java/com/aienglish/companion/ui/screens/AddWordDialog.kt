package com.aienglish.companion.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.unit.dp
import com.aienglish.companion.data.api.ApiResult
import com.aienglish.companion.data.api.VocabularyWord
import com.aienglish.companion.ui.LocalAppContainer
import kotlinx.coroutines.launch

/** Type a word in by hand (AE-5) — e.g. mid-conversation, so as not to
 * interrupt the character. Only the word is needed: the server fills in
 * the translation and explanation itself, after the conversation. */
@Composable
fun AddWordDialog(onDismiss: () -> Unit, onAdded: (VocabularyWord) -> Unit) {
    val api = LocalAppContainer.current.apiClient
    val scope = rememberCoroutineScope()
    var word by remember { mutableStateOf("") }
    var translation by remember { mutableStateOf("") }
    var saving by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { focus.requestFocus() }

    fun save() {
        if (word.isBlank() || saving) return
        saving = true
        error = null
        scope.launch {
            when (val result = api.addVocabulary(word.trim(), translation.trim().ifBlank { null })) {
                is ApiResult.Success -> onAdded(result.data)
                is ApiResult.HttpError -> error =
                    if (result.code == 422) "Enter a word or a short expression (up to 8 words)."
                    else "Server error ${result.code}"
                is ApiResult.NetworkError -> error = "Can't reach the server."
            }
            saving = false
        }
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Add a word") },
        text = {
            Column {
                OutlinedTextField(
                    value = word,
                    onValueChange = { word = it },
                    label = { Text("Word or expression") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.None, imeAction = ImeAction.Next),
                    modifier = Modifier.fillMaxWidth().focusRequester(focus),
                )
                OutlinedTextField(
                    value = translation,
                    onValueChange = { translation = it },
                    label = { Text("Translation (optional)") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                    keyboardActions = KeyboardActions(onDone = { save() }),
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                )
                Text(
                    error ?: "Translation and meaning are filled in automatically after the conversation.",
                    style = MaterialTheme.typography.bodySmall,
                    color = if (error != null) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 8.dp),
                )
            }
        },
        confirmButton = { TextButton(onClick = { save() }, enabled = word.isNotBlank() && !saving) { Text("Add") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}
