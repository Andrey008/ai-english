package com.aienglish.companion.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.aienglish.companion.data.ServerConfigStore

/** First-run entry for the server address and this device's token — no
 * server discovery exists, this is always manual (STORY-05-01, ADR-0017).
 * Also shown again when an older install has an address but no token yet.
 * Settings edits the same values later (STORY-05-10). */
@Composable
fun ServerSetupScreen(store: ServerConfigStore, onSaved: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .safeDrawingPadding()
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Text("Connect to your server", style = MaterialTheme.typography.headlineSmall)
        Text(
            "Enter the Mac server's address and this phone's access token " +
                "(run scripts/devices.py create on the Mac).",
            style = MaterialTheme.typography.bodyMedium,
            modifier = Modifier.padding(bottom = 24.dp, top = 8.dp),
        )
        ServerConnectionForm(store = store, onSaved = onSaved)
    }
}
