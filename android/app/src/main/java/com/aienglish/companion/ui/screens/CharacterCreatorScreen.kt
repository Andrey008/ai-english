package com.aienglish.companion.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.HelpOutline
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.aienglish.companion.data.api.ApiResult
import com.aienglish.companion.data.api.CharacterPreset
import com.aienglish.companion.data.api.CorrectionStyle
import com.aienglish.companion.data.api.Gender
import com.aienglish.companion.data.api.TtsEngine
import com.aienglish.companion.ui.LocalAppContainer
import kotlinx.coroutines.launch

/** Every structured `CharacterPreset` field (`ADR-0008`) except
 * `voice_reference_path` (XTTS cloning isn't implemented server-side —
 * deferred, not built here) and `system_prompt_override` (escape hatch,
 * "expected unused in practice" per `presets.py`). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CharacterCreatorScreen(characterId: String?, onDone: () -> Unit, onOpenGuide: () -> Unit = {}) {
    val appContainer = LocalAppContainer.current
    val scope = rememberCoroutineScope()
    val isEdit = characterId != null

    var loading by remember { mutableStateOf(isEdit) }
    var submitting by remember { mutableStateOf(false) }
    var errorMessage by remember { mutableStateOf<String?>(null) }

    var id by remember { mutableStateOf(characterId ?: "") }
    var name by remember { mutableStateOf("") }
    var gender by remember { mutableStateOf(Gender.FEMALE) }
    var accent by remember { mutableStateOf("en_US") }
    var roleDescription by remember { mutableStateOf("") }
    var ttsVoiceId by remember { mutableStateOf("") }
    var ttsEngine by remember { mutableStateOf(TtsEngine.KOKORO) }
    var temperature by remember { mutableFloatStateOf(0.7f) }
    var correctionStyle by remember { mutableStateOf(CorrectionStyle.OFF) }
    var memoryEnabled by remember { mutableStateOf(true) }

    var showResetMemoryConfirm by remember { mutableStateOf(false) }
    var resettingMemory by remember { mutableStateOf(false) }
    var memoryResetMessage by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(characterId) {
        if (characterId == null) return@LaunchedEffect
        loading = true
        when (val result = appContainer.apiClient.getCharacter(characterId)) {
            is ApiResult.Success -> {
                val c = result.data
                id = c.id
                name = c.name
                gender = c.gender
                accent = c.accent
                roleDescription = c.roleDescription
                ttsVoiceId = c.ttsVoiceId
                ttsEngine = c.ttsEngine
                temperature = c.temperature.toFloat()
                correctionStyle = c.correctionStyle
                memoryEnabled = c.memoryEnabled
            }
            is ApiResult.HttpError -> errorMessage = "Couldn't load character (server error ${result.code})"
            is ApiResult.NetworkError -> errorMessage = "Can't reach server — check Settings for the correct host/port."
        }
        loading = false
    }

    fun submit() {
        if (id.isBlank() || name.isBlank() || roleDescription.isBlank() || ttsVoiceId.isBlank()) {
            errorMessage = "Fill in ID, name, role description, and TTS voice ID."
            return
        }
        val preset = CharacterPreset(
            id = id.trim(),
            name = name.trim(),
            gender = gender,
            accent = accent.trim().ifBlank { "en_US" },
            roleDescription = roleDescription.trim(),
            ttsVoiceId = ttsVoiceId.trim(),
            ttsEngine = ttsEngine,
            temperature = temperature.toDouble(),
            correctionStyle = correctionStyle,
            memoryEnabled = memoryEnabled,
        )
        scope.launch {
            submitting = true
            errorMessage = null
            val result = if (isEdit) {
                appContainer.apiClient.updateCharacter(id, preset)
            } else {
                appContainer.apiClient.createCharacter(preset)
            }
            submitting = false
            when (result) {
                is ApiResult.Success -> onDone()
                is ApiResult.HttpError -> errorMessage = "Server error ${result.code}: ${result.body ?: "no details"}"
                is ApiResult.NetworkError -> errorMessage = "Can't reach server — check Settings for the correct host/port."
            }
        }
    }

    fun resetMemory() {
        scope.launch {
            resettingMemory = true
            memoryResetMessage = null
            when (val result = appContainer.apiClient.deleteCharacterMemory(id)) {
                is ApiResult.Success -> memoryResetMessage = "Memory cleared — $name won't recall past sessions."
                is ApiResult.HttpError -> memoryResetMessage = "Server error ${result.code}: ${result.body ?: "no details"}"
                is ApiResult.NetworkError -> memoryResetMessage = "Can't reach server — check Settings for the correct host/port."
            }
            resettingMemory = false
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(if (isEdit) "Edit character" else "Create character") },
                navigationIcon = {
                    IconButton(onClick = onDone) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back") }
                },
                actions = {
                    TextButton(onClick = onOpenGuide) {
                        Icon(Icons.AutoMirrored.Filled.HelpOutline, contentDescription = null, modifier = Modifier.size(18.dp))
                        Text("Guide", modifier = Modifier.padding(start = 6.dp))
                    }
                },
            )
        },
    ) { padding ->
        if (loading) {
            Box(modifier = Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
            return@Scaffold
        }

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
        ) {
            OutlinedTextField(
                value = id,
                onValueChange = { id = it },
                label = { Text("ID (slug)") },
                enabled = !isEdit,
                singleLine = true,
                modifier = Modifier.fillMaxWidth().padding(bottom = 12.dp),
            )
            OutlinedTextField(
                value = name,
                onValueChange = { name = it },
                label = { Text("Name") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth().padding(bottom = 12.dp),
            )
            EnumChoiceField("Gender", listOf(Gender.FEMALE to "Female", Gender.MALE to "Male"), gender) { gender = it }
            OutlinedTextField(
                value = accent,
                onValueChange = { accent = it },
                label = { Text("Accent") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 12.dp),
            )
            OutlinedTextField(
                value = roleDescription,
                onValueChange = { roleDescription = it },
                label = { Text("Role description") },
                minLines = 4,
                modifier = Modifier.fillMaxWidth().padding(bottom = 12.dp),
            )
            OutlinedTextField(
                value = ttsVoiceId,
                onValueChange = { ttsVoiceId = it },
                label = { Text("TTS voice ID") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth().padding(bottom = 12.dp),
            )
            EnumChoiceField("TTS engine", listOf(TtsEngine.KOKORO to "Kokoro", TtsEngine.PIPER to "Piper", TtsEngine.XTTS to "XTTS"), ttsEngine) { ttsEngine = it }
            Text(
                "Temperature: ${"%.2f".format(temperature)}",
                style = MaterialTheme.typography.labelLarge,
                modifier = Modifier.padding(top = 12.dp),
            )
            Slider(value = temperature, onValueChange = { temperature = it }, valueRange = 0f..2f)
            EnumChoiceField(
                "Correction style",
                listOf(
                    CorrectionStyle.OFF to "Off",
                    CorrectionStyle.END_OF_SESSION to "End of session",
                    CorrectionStyle.LIVE_GENTLE to "Live gentle",
                ),
                correctionStyle,
            ) { correctionStyle = it }
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
            ) {
                Text("Memory enabled", style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
                Switch(checked = memoryEnabled, onCheckedChange = { memoryEnabled = it })
            }
            if (isEdit) {
                OutlinedButton(
                    onClick = { showResetMemoryConfirm = true },
                    enabled = !resettingMemory,
                    modifier = Modifier.fillMaxWidth().padding(top = 16.dp),
                ) {
                    Text(if (resettingMemory) "Resetting…" else "Reset memory")
                }
                memoryResetMessage?.let {
                    Text(
                        it,
                        style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier.padding(top = 8.dp),
                    )
                }
            }
            errorMessage?.let {
                Text(
                    it,
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.padding(top = 16.dp),
                )
            }
            Button(
                onClick = { submit() },
                enabled = !submitting,
                modifier = Modifier.fillMaxWidth().padding(top = 16.dp, bottom = 24.dp),
            ) {
                if (submitting) {
                    CircularProgressIndicator(modifier = Modifier.size(20.dp))
                } else {
                    Text(if (isEdit) "Save" else "Create")
                }
            }
        }
    }

    if (showResetMemoryConfirm) {
        AlertDialog(
            onDismissRequest = { showResetMemoryConfirm = false },
            title = { Text("Reset memory?") },
            text = { Text("$name will forget everything remembered from past sessions with this character. This can't be undone.") },
            confirmButton = {
                TextButton(onClick = {
                    showResetMemoryConfirm = false
                    resetMemory()
                }) { Text("Reset") }
            },
            dismissButton = {
                TextButton(onClick = { showResetMemoryConfirm = false }) { Text("Cancel") }
            },
        )
    }
}

@Composable
private fun <T> EnumChoiceField(label: String, options: List<Pair<T, String>>, selected: T, onSelect: (T) -> Unit) {
    Column(modifier = Modifier.padding(top = 8.dp)) {
        Text(label, style = MaterialTheme.typography.labelLarge)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(top = 4.dp)) {
            options.forEach { (value, text) ->
                FilterChip(selected = value == selected, onClick = { onSelect(value) }, label = { Text(text) })
            }
        }
    }
}
