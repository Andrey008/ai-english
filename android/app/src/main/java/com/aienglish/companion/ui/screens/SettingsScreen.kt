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
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

private fun testConnectionClient(): OkHttpClient = OkHttpClient.Builder()
    .connectTimeout(4, TimeUnit.SECONDS)
    .readTimeout(4, TimeUnit.SECONDS)
    .build()

/** Result of hitting `/healthz` against whatever host/port is currently
 * typed in the form — deliberately not [com.aienglish.companion.data.api.ApiClient],
 * which always reads the *saved* config; this needs to test unsaved values
 * before the user commits to them. */
private sealed class ConnectionTestResult {
    object Reachable : ConnectionTestResult()
    data class Unreachable(val reason: String) : ConnectionTestResult()
}

private suspend fun testConnection(host: String, port: Int): ConnectionTestResult = withContext(Dispatchers.IO) {
    try {
        val request = Request.Builder().url("http://$host:$port/healthz").build()
        testConnectionClient().newCall(request).execute().use { response ->
            if (response.isSuccessful) {
                ConnectionTestResult.Reachable
            } else {
                ConnectionTestResult.Unreachable("Server responded with HTTP ${response.code}")
            }
        }
    } catch (e: Exception) {
        ConnectionTestResult.Unreachable(e.message ?: e.javaClass.simpleName)
    }
}

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

    var host by remember { mutableStateOf("") }
    var portText by remember { mutableStateOf("8000") }

    LaunchedEffect(Unit) {
        val config = appContainer.serverConfigStore.configFlow.first()
        host = config.host
        portText = config.port.toString()
    }

    val sessionActive by appContainer.wsSessionClient.sessionActiveFlow.collectAsState()
    val defaultLevel by appContainer.englishLevelStore.defaultLevelFlow.collectAsState(initial = EnglishLevel.DEFAULT)
    val appearance by appContainer.appearanceStore.appearanceFlow.collectAsState(initial = Appearance())

    var saving by remember { mutableStateOf(false) }
    var saveMessage by remember { mutableStateOf<String?>(null) }
    var testing by remember { mutableStateOf(false) }
    var testResult by remember { mutableStateOf<ConnectionTestResult?>(null) }

    fun save() {
        val port = portText.toIntOrNull() ?: return
        scope.launch {
            saving = true
            saveMessage = null
            appContainer.serverConfigStore.save(host.trim(), port)
            saving = false
            saveMessage = "Saved."
        }
    }

    fun test() {
        val port = portText.toIntOrNull() ?: return
        scope.launch {
            testing = true
            testResult = null
            testResult = testConnection(host.trim(), port)
            testing = false
        }
    }

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
                OutlinedTextField(
                    value = host,
                    onValueChange = { host = it },
                    label = { Text("Host") },
                    singleLine = true,
                    enabled = !sessionActive,
                    modifier = Modifier.fillMaxWidth().padding(bottom = 12.dp),
                )
                OutlinedTextField(
                    value = portText,
                    onValueChange = { portText = it.filter(Char::isDigit) },
                    label = { Text("Port") },
                    singleLine = true,
                    enabled = !sessionActive,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    modifier = Modifier.fillMaxWidth().padding(bottom = 16.dp),
                )
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Button(
                        onClick = { save() },
                        enabled = !sessionActive && !saving && host.isNotBlank() && portText.isNotBlank(),
                    ) {
                        if (saving) CircularProgressIndicator(modifier = Modifier.size(20.dp)) else Text("Save")
                    }
                    OutlinedButton(
                        onClick = { test() },
                        enabled = !testing && host.isNotBlank() && portText.isNotBlank(),
                    ) {
                        Text(if (testing) "Testing…" else "Test connection")
                    }
                }
                saveMessage?.let {
                    Text(it, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 8.dp))
                }
                testResult?.let { result ->
                    val (message, color) = when (result) {
                        is ConnectionTestResult.Reachable -> "Reachable." to MaterialTheme.colorScheme.primary
                        is ConnectionTestResult.Unreachable -> "Unreachable: ${result.reason}" to MaterialTheme.colorScheme.error
                    }
                    Text(message, style = MaterialTheme.typography.bodyMedium, color = color, modifier = Modifier.padding(top = 8.dp))
                }
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
