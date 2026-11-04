package com.aienglish.companion.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/** Server host/port (or Tailscale hostname) the app connects to — no discovery
 * mechanism exists server-side, this is always manually entered (STORY-05-01). */
data class ServerConfig(
    val host: String = "",
    val port: Int = 8000,
) {
    val isConfigured: Boolean get() = host.isNotBlank()
}

private val Context.serverConfigDataStore: DataStore<Preferences> by preferencesDataStore(
    name = "server_config"
)

class ServerConfigStore(private val context: Context) {
    private val keyHost = stringPreferencesKey("host")
    private val keyPort = intPreferencesKey("port")

    val configFlow: Flow<ServerConfig> = context.serverConfigDataStore.data.map { prefs ->
        ServerConfig(
            host = prefs[keyHost] ?: "",
            port = prefs[keyPort] ?: 8000,
        )
    }

    suspend fun save(host: String, port: Int) {
        context.serverConfigDataStore.edit { prefs ->
            prefs[keyHost] = host
            prefs[keyPort] = port
        }
    }
}
