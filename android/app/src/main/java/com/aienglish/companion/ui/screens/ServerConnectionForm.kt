package com.aienglish.companion.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import com.aienglish.companion.data.ServerConfig
import com.aienglish.companion.data.ServerConfigStore
import com.aienglish.companion.data.api.ApiClient
import com.aienglish.companion.data.api.ApiResult
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit

private fun testConnectionClient(): OkHttpClient = OkHttpClient.Builder()
    .connectTimeout(5, TimeUnit.SECONDS)
    .readTimeout(5, TimeUnit.SECONDS)
    .build()

private sealed class ConnectionTestResult {
    data class Ok(val deviceName: String?) : ConnectionTestResult()
    data class Failed(val reason: String) : ConnectionTestResult()
}

/** Checks the values typed in the form, before they are saved, with
 * `GET /auth/me` — address and token in one call (ADR-0017). */
private suspend fun testConnection(config: ServerConfig): ConnectionTestResult {
    config.connectProblem?.let { return ConnectionTestResult.Failed(it) }
    return when (val result = ApiClient({ config }, testConnectionClient()).authMe()) {
        is ApiResult.Success -> ConnectionTestResult.Ok(result.data.device?.name)
        is ApiResult.HttpError ->
            if (result.code == 401) ConnectionTestResult.Failed("the server rejected this token")
            else ConnectionTestResult.Failed("server responded with HTTP ${result.code}")
        is ApiResult.NetworkError ->
            ConnectionTestResult.Failed(result.cause.message ?: result.cause.javaClass.simpleName)
    }
}

/** Host, port, HTTPS and device token — the first-run setup screen and
 * Settings share it. [onSaved] runs after the config is stored. */
@Composable
fun ServerConnectionForm(
    store: ServerConfigStore,
    enabled: Boolean = true,
    onSaved: () -> Unit = {},
) {
    val scope = rememberCoroutineScope()
    var host by remember { mutableStateOf("") }
    var portText by remember { mutableStateOf("8000") }
    var useTls by remember { mutableStateOf(false) }
    var token by remember { mutableStateOf("") }
    var showToken by remember { mutableStateOf(false) }
    var saving by remember { mutableStateOf(false) }
    var saveMessage by remember { mutableStateOf<String?>(null) }
    var testing by remember { mutableStateOf(false) }
    var testResult by remember { mutableStateOf<ConnectionTestResult?>(null) }

    LaunchedEffect(Unit) {
        val saved = store.configFlow.first()
        host = saved.host
        portText = saved.port.toString()
        useTls = saved.useTls
        token = saved.token
    }

    fun current(): ServerConfig? = portText.toIntOrNull()?.let {
        ServerConfig(host = host.trim(), port = it, useTls = useTls, token = token.trim())
    }

    val draft = current()
    val formFilled = draft != null && draft.host.isNotBlank() && draft.token.isNotBlank()

    Column {
        OutlinedTextField(
            value = host,
            onValueChange = { host = it; testResult = null },
            label = { Text("Host") },
            singleLine = true,
            enabled = enabled,
            modifier = Modifier.fillMaxWidth().padding(bottom = 12.dp),
        )
        OutlinedTextField(
            value = portText,
            onValueChange = { portText = it.filter(Char::isDigit); testResult = null },
            label = { Text("Port") },
            singleLine = true,
            enabled = enabled,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            modifier = Modifier.fillMaxWidth(),
        )
        SwitchRow(
            title = "Use HTTPS",
            subtitle = "On for a public address behind TLS (port 443). Off for LAN or Tailscale.",
            checked = useTls,
            onCheckedChange = { if (enabled) { useTls = it; testResult = null } },
        )
        OutlinedTextField(
            value = token,
            onValueChange = { token = it; testResult = null },
            label = { Text("Access token") },
            supportingText = { Text("From server/scripts/devices.py create") },
            singleLine = true,
            enabled = enabled,
            visualTransformation = if (showToken) VisualTransformation.None else PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, autoCorrectEnabled = false),
            trailingIcon = {
                IconButton(onClick = { showToken = !showToken }) {
                    Icon(
                        if (showToken) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                        contentDescription = if (showToken) "Hide token" else "Show token",
                    )
                }
            },
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 8.dp),
        )
        if (draft != null && draft.host.isNotBlank() && draft.cleartextBlocked) {
            Text(
                "This looks like a public address: turn on HTTPS, the app won't send the token unencrypted.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.padding(bottom = 8.dp),
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.padding(top = 8.dp)) {
            Button(
                onClick = {
                    val config = current() ?: return@Button
                    scope.launch {
                        saving = true
                        saveMessage = null
                        store.save(config)
                        saving = false
                        saveMessage = "Saved."
                        onSaved()
                    }
                },
                enabled = enabled && !saving && formFilled,
            ) {
                if (saving) CircularProgressIndicator(modifier = Modifier.size(20.dp)) else Text("Save")
            }
            OutlinedButton(
                onClick = {
                    val config = current() ?: return@OutlinedButton
                    scope.launch {
                        testing = true
                        testResult = null
                        testResult = testConnection(config)
                        testing = false
                    }
                },
                enabled = !testing && formFilled,
            ) {
                Text(if (testing) "Testing…" else "Test connection")
            }
        }
        saveMessage?.let {
            Text(it, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 8.dp))
        }
        testResult?.let { result ->
            val (message, color) = when (result) {
                is ConnectionTestResult.Ok ->
                    (result.deviceName?.let { "Connected as \"$it\"." } ?: "Connected.") to MaterialTheme.colorScheme.primary
                is ConnectionTestResult.Failed -> "Can't connect: ${result.reason}" to MaterialTheme.colorScheme.error
            }
            Text(message, style = MaterialTheme.typography.bodyMedium, color = color, modifier = Modifier.padding(top = 8.dp))
        }
    }
}
