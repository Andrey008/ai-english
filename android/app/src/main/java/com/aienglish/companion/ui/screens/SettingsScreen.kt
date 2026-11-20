package com.aienglish.companion.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Dns
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Palette
import androidx.compose.material.icons.filled.School
import androidx.compose.material3.Button
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.LargeTopAppBar
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
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
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.aienglish.companion.BuildConfig
import com.aienglish.companion.R
import com.aienglish.companion.data.Appearance
import com.aienglish.companion.data.EnglishLevel
import com.aienglish.companion.data.ThemeMode
import com.aienglish.companion.ui.LocalAppContainer
import kotlinx.coroutines.launch

/** Appearance (light/dark theme, wallpaper colors), default English level,
 * editable server connection config (supersedes STORY-05-01's first-run-only
 * entry) and app version info. Per-character memory reset lives on the
 * Character Creator/edit screen instead (STORY-05-10) — it needs a specific
 * character in context, which this screen doesn't have. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen() {
    val appContainer = LocalAppContainer.current
    val scope = rememberCoroutineScope()

    val sessionActive by appContainer.wsSessionClient.sessionActiveFlow.collectAsState()
    val defaultLevel by appContainer.englishLevelStore.defaultLevelFlow.collectAsState(initial = EnglishLevel.DEFAULT)
    val appearance by appContainer.appearanceStore.appearanceFlow.collectAsState(initial = Appearance())

    Scaffold(topBar = { LargeTopAppBar(title = { Text("Settings") }) }) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            SettingsCard(title = "Appearance", icon = Icons.Default.Palette) {
                Text("Theme", style = MaterialTheme.typography.bodyLarge, modifier = Modifier.padding(bottom = 8.dp))
                SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
                    ThemeMode.entries.forEachIndexed { index, mode ->
                        SegmentedButton(
                            selected = appearance.themeMode == mode,
                            onClick = { scope.launch { appContainer.appearanceStore.setThemeMode(mode) } },
                            shape = SegmentedButtonDefaults.itemShape(index, ThemeMode.entries.size),
                            icon = {},
                        ) { Text(mode.label) }
                    }
                }
                SwitchRow(
                    title = "Wallpaper colors",
                    subtitle = "Take the app's colors from your wallpaper instead of its own palette.",
                    checked = appearance.wallpaperColors,
                    onCheckedChange = { enabled -> scope.launch { appContainer.appearanceStore.setWallpaperColors(enabled) } },
                )
            }

            SettingsCard(title = "Your English level", icon = Icons.Default.School) {
                Text(
                    "Preselected for every new conversation — characters keep their words and sentences at this level. You can still change it per conversation.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(bottom = 12.dp),
                )
                EnglishLevelPicker(
                    selected = defaultLevel,
                    onSelect = { level -> scope.launch { appContainer.englishLevelStore.setDefault(level) } },
                )
            }

            SettingsCard(title = "Server connection", icon = Icons.Default.Dns) {
                if (sessionActive) {
                    Text(
                        "A conversation is active — end it before changing the server address.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.error,
                        modifier = Modifier.padding(bottom = 12.dp),
                    )
                }
                ServerConnectionForm(store = appContainer.serverConfigStore, enabled = !sessionActive)
            }

            SettingsCard(title = "About", icon = Icons.Default.Info) {
                Text(
                    "${stringResource(R.string.app_name)} ${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})",
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
        }
    }
}

@Composable
private fun SettingsCard(title: String, icon: ImageVector, content: @Composable ColumnScope.() -> Unit) {
    ElevatedCard(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.elevatedCardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLow),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(bottom = 12.dp)) {
                Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                Text(title, style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(start = 12.dp))
            }
            content()
        }
    }
}
