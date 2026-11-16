package com.aienglish.companion.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/** Where the server is and how to authenticate to it — always entered by
 * hand, there is no discovery (STORY-05-01).
 *
 * [token] is this device's API token from `server/scripts/devices.py
 * create` (ADR-0017), sent as `Authorization: Bearer` on every HTTP call
 * and on the WebSocket upgrade. [useTls] picks https/wss for a server
 * behind TLS; over Tailscale it stays plain http. It lives in app-private
 * DataStore; the app is excluded from cloud backup and device transfer
 * (manifest). */
data class ServerConfig(
    val host: String = "",
    val port: Int = 8000,
    val useTls: Boolean = false,
    val token: String = "",
) {
    val isConfigured: Boolean get() = host.isNotBlank() && token.isNotBlank()

    val baseUrl: String get() = "${if (useTls) "https" else "http"}://$host:$port"

    val authorizationHeader: String get() = "Bearer $token"

    /** A token sent over plain HTTP can be read by anyone on the path, so
     * only allow that to addresses that never leave a private network:
     * loopback, LAN, the emulator host and Tailscale. */
    val cleartextBlocked: Boolean get() = !useTls && !isPrivateHost(host.trim())

    /** Why [ApiClient]/[WsSessionClient] refuse to connect, or null. */
    val connectProblem: String?
        get() = when {
            host.isBlank() -> "No server address set."
            token.isBlank() -> "No access token set (Settings → Server connection)."
            cleartextBlocked -> "Turn on HTTPS: the token can't be sent unencrypted to a public address."
            else -> null
        }
}

/** True for hosts whose traffic stays on a private network. */
fun isPrivateHost(host: String): Boolean {
    val h = host.lowercase().trimEnd('.')
    if (h.isEmpty()) return false
    if (h == "localhost" || h.endsWith(".local") || h.endsWith(".ts.net")) return true
    // A bare name (no dots) only resolves on the LAN or via Tailscale MagicDNS.
    if (!h.contains('.') && !h.contains(':')) return true
    val parts = h.split('.').map { it.toIntOrNull() ?: return false }
    if (parts.size != 4 || parts.any { it !in 0..255 }) return false
    val (a, b) = parts
    return a == 127 || a == 10 ||
        (a == 192 && b == 168) ||
        (a == 172 && b in 16..31) ||
        (a == 100 && b in 64..127) // CGNAT range, used by Tailscale
}

private val Context.serverConfigDataStore: DataStore<Preferences> by preferencesDataStore(
    name = "server_config"
)

class ServerConfigStore(private val context: Context) {
    private val keyHost = stringPreferencesKey("host")
    private val keyPort = intPreferencesKey("port")
    private val keyUseTls = booleanPreferencesKey("use_tls")
    private val keyToken = stringPreferencesKey("token")

    val configFlow: Flow<ServerConfig> = context.serverConfigDataStore.data.map { prefs ->
        ServerConfig(
            host = prefs[keyHost] ?: "",
            port = prefs[keyPort] ?: 8000,
            useTls = prefs[keyUseTls] ?: false,
            token = prefs[keyToken] ?: "",
        )
    }

    suspend fun save(config: ServerConfig) {
        context.serverConfigDataStore.edit { prefs ->
            prefs[keyHost] = config.host.trim()
            prefs[keyPort] = config.port
            prefs[keyUseTls] = config.useTls
            prefs[keyToken] = config.token.trim()
        }
    }
}
