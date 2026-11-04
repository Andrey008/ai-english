package com.aienglish.companion

import android.content.Context
import com.aienglish.companion.data.CharacterSelectionStore
import com.aienglish.companion.data.ServerConfigStore
import com.aienglish.companion.data.api.ApiClient
import com.aienglish.companion.data.audio.AudioCapture
import com.aienglish.companion.data.audio.AudioPlayback
import com.aienglish.companion.data.audio.AudioSessionController
import com.aienglish.companion.data.ws.WsSessionClient

/** Composition root (ADR-0009 — no DI framework). Constructed once in
 * [MainActivity] and threaded through Compose via [LocalAppContainer]. */
class AppContainer(context: Context) {
    val serverConfigStore = ServerConfigStore(context.applicationContext)
    val apiClient = ApiClient(serverConfigStore)
    val characterSelectionStore = CharacterSelectionStore(context.applicationContext)
    val wsSessionClient = WsSessionClient(serverConfigStore)
    val audioCapture = AudioCapture(context.applicationContext)
    val audioPlayback = AudioPlayback(context.applicationContext)
    val audioSessionController = AudioSessionController(wsSessionClient, audioCapture, audioPlayback)
}
