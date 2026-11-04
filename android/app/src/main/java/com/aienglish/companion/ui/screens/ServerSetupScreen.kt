package com.aienglish.companion.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.aienglish.companion.data.ServerConfigStore
import kotlinx.coroutines.launch

/** First-run entry for the server's host/port (or Tailscale hostname) — no
 * server-discovery mechanism exists, this is always manual (STORY-05-01).
 * Editing it later is STORY-05-10's job (full Settings screen). */
@Composable
fun ServerSetupScreen(store: ServerConfigStore, onSaved: () -> Unit) {
    var host by remember { mutableStateOf("") }
    var portText by remember { mutableStateOf("8000") }
    val scope = rememberCoroutineScope()

    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("Connect to your server", style = MaterialTheme.typography.headlineSmall)
        Text(
            "Enter the Mac server's Tailscale hostname or IP.",
            style = MaterialTheme.typography.bodyMedium,
            modifier = Modifier.padding(bottom = 24.dp, top = 8.dp),
        )
        OutlinedTextField(
            value = host,
            onValueChange = { host = it },
            label = { Text("Host") },
            singleLine = true,
            modifier = Modifier.padding(bottom = 12.dp),
        )
        OutlinedTextField(
            value = portText,
            onValueChange = { portText = it.filter(Char::isDigit) },
            label = { Text("Port") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            modifier = Modifier.padding(bottom = 24.dp),
        )
        Button(
            enabled = host.isNotBlank() && portText.isNotBlank(),
            onClick = {
                val port = portText.toIntOrNull() ?: return@Button
                scope.launch {
                    store.save(host.trim(), port)
                    onSaved()
                }
            },
        ) {
            Text("Save")
        }
    }
}
