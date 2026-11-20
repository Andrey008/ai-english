package com.aienglish.companion.ui.screens

import android.widget.Toast
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Call
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material3.Button
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.Surface
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.aienglish.companion.data.EnglishLevel
import com.aienglish.companion.data.api.ApiResult
import com.aienglish.companion.data.api.CharacterPreset
import com.aienglish.companion.data.api.ScenarioDefinition
import com.aienglish.companion.service.SessionStartRequest
import com.aienglish.companion.ui.LocalAppContainer
import com.aienglish.companion.ui.components.Avatar
import com.aienglish.companion.ui.components.SectionHeader
import kotlinx.coroutines.launch

/** Character, scenario, level and memory for a new conversation, then
 * Start (ADR-0015 — this replaces the old Session tab's start screen).
 * The character picked here is remembered as the default for next time. */
@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun NewConversationScreen(onBack: () -> Unit, onStarted: () -> Unit) {
    val appContainer = LocalAppContainer.current
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val mic = rememberMicPermission()

    var characters by remember { mutableStateOf<List<CharacterPreset>?>(null) }
    var loadError by remember { mutableStateOf<String?>(null) }
    var scenarios by remember { mutableStateOf<List<ScenarioDefinition>>(emptyList()) }
    var selectedScenarioId by remember { mutableStateOf<String?>(null) }
    val selectedCharacterId by appContainer.characterSelectionStore.selectedIdFlow.collectAsState(initial = null)

    // Per-conversation choices: the level starts from the Settings default
    // and re-syncs if that changes; neither is written back from here.
    val defaultLevel by appContainer.englishLevelStore.defaultLevelFlow.collectAsState(initial = EnglishLevel.DEFAULT)
    var level by remember { mutableStateOf(EnglishLevel.DEFAULT) }
    LaunchedEffect(defaultLevel) { level = defaultLevel }
    var useMemory by remember { mutableStateOf(true) }
    val forcePhoneMic by appContainer.audioPrefsStore.forcePhoneMicFlow.collectAsState(initial = false)

    LaunchedEffect(Unit) { appContainer.apiClient.warmup() }

    LaunchedEffect(Unit) {
        when (val result = appContainer.apiClient.listCharacters()) {
            is ApiResult.Success -> characters = result.data
            else -> loadError = "Can't reach the server — check Settings for the host/port."
        }
        when (val result = appContainer.apiClient.listScenarios()) {
            is ApiResult.Success -> scenarios = result.data
            else -> Unit // freeform still works without scenario content
        }
    }

    val character = characters?.let { list -> list.firstOrNull { it.id == selectedCharacterId } ?: list.firstOrNull() }

    fun start() {
        val chosen = character ?: return
        val captureStarted = appContainer.voiceSessionLauncher.start(
            context,
            SessionStartRequest(
                characterName = chosen.name,
                characterId = chosen.id,
                scenarioId = selectedScenarioId,
                englishLevel = level.id,
                useMemory = useMemory,
                useHeadsetMic = !forcePhoneMic,
            ),
        )
        if (!captureStarted) {
            Toast.makeText(context, "Microphone unavailable — the character won't hear you.", Toast.LENGTH_LONG).show()
        }
        onStarted()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("New conversation") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        },
        bottomBar = {
            if (character != null) {
                Surface(color = MaterialTheme.colorScheme.surfaceContainer) {
                    Box(modifier = Modifier.fillMaxWidth().navigationBarsPadding().padding(horizontal = 16.dp, vertical = 12.dp)) {
                        if (mic.granted) {
                            Button(onClick = { start() }, modifier = Modifier.fillMaxWidth().height(56.dp)) {
                                Icon(Icons.Default.Call, contentDescription = null)
                                Text("Start talking with ${character.name}", modifier = Modifier.padding(start = 8.dp))
                            }
                        } else {
                            Button(onClick = mic.request, modifier = Modifier.fillMaxWidth().height(56.dp)) {
                                Icon(Icons.Default.Mic, contentDescription = null)
                                Text("Allow microphone to start", modifier = Modifier.padding(start = 8.dp))
                            }
                        }
                    }
                }
            }
        },
    ) { padding ->
        Column(
            modifier = Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()).padding(vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(20.dp),
        ) {
            loadError?.let {
                Text(it, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(16.dp))
                return@Column
            }
            val list = characters
            if (list == null) {
                Box(Modifier.fillMaxWidth().padding(48.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
                return@Column
            }
            if (list.isEmpty()) {
                Text(
                    "Create a character on the Characters tab first.",
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.padding(16.dp),
                )
                return@Column
            }

            Column {
                SectionHeader("Who do you want to talk to?", Modifier.padding(horizontal = 16.dp))
                LazyRow(
                    contentPadding = PaddingValues(horizontal = 16.dp, vertical = 12.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    items(list, key = { it.id }) { preset ->
                        CharacterCard(
                            preset = preset,
                            selected = preset.id == character?.id,
                            onClick = { scope.launch { appContainer.characterSelectionStore.select(preset.id) } },
                        )
                    }
                }
            }

            Column(modifier = Modifier.padding(horizontal = 16.dp)) {
                SectionHeader("Scenario", Modifier.padding(bottom = 8.dp))
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FilterChip(
                        selected = selectedScenarioId == null,
                        onClick = { selectedScenarioId = null },
                        label = { Text("Free chat") },
                    )
                    scenarios.forEach { scenario ->
                        FilterChip(
                            selected = selectedScenarioId == scenario.id,
                            onClick = { selectedScenarioId = scenario.id },
                            label = { Text(scenario.title) },
                        )
                    }
                }
            }

            Column(modifier = Modifier.padding(horizontal = 16.dp)) {
                SectionHeader("Your English level", Modifier.padding(bottom = 8.dp))
                EnglishLevelPicker(selected = level, onSelect = { level = it })
            }

            Column(modifier = Modifier.padding(horizontal = 16.dp)) {
                SectionHeader("Options")
                SwitchRow(
                    title = "Remember past conversations",
                    subtitle = "Off: ${character?.name ?: "the character"} starts without what they know about you.",
                    checked = useMemory,
                    onCheckedChange = { useMemory = it },
                )
                SwitchRow(
                    title = "Use phone microphone",
                    subtitle = "Records with the phone even when a Bluetooth headset is connected: clearer sound, but keep the phone close.",
                    checked = forcePhoneMic,
                    onCheckedChange = { enabled -> scope.launch { appContainer.audioPrefsStore.setForcePhoneMic(enabled) } },
                )
            }
        }
    }
}

@Composable
private fun CharacterCard(preset: CharacterPreset, selected: Boolean, onClick: () -> Unit) {
    val border = if (selected) BorderStroke(2.dp, MaterialTheme.colorScheme.primary) else null
    OutlinedCard(
        onClick = onClick,
        border = border ?: CardDefaults.outlinedCardBorder(),
        colors = CardDefaults.outlinedCardColors(
            containerColor = if (selected) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceContainerLow,
        ),
        modifier = Modifier.width(132.dp),
    ) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(vertical = 16.dp, horizontal = 8.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Box {
                Avatar(preset.name, size = 56.dp)
                if (selected) {
                    Icon(
                        Icons.Default.CheckCircle,
                        contentDescription = "Selected",
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.align(Alignment.BottomEnd).size(20.dp)
                            .background(MaterialTheme.colorScheme.surface, CircleShape),
                    )
                }
            }
            Text(
                preset.name,
                style = MaterialTheme.typography.titleSmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.padding(top = 10.dp),
            )
            Text(
                preset.roleDescription,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 2,
                minLines = 2,
                overflow = TextOverflow.Ellipsis,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(top = 2.dp),
            )
        }
    }
}

@Composable
fun SwitchRow(title: String, subtitle: String, checked: Boolean, onCheckedChange: (Boolean) -> Unit) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.fillMaxWidth().padding(top = 16.dp),
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            Text(subtitle, style = MaterialTheme.typography.bodySmall)
        }
        Switch(checked = checked, onCheckedChange = onCheckedChange)
    }
}
