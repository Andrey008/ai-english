package com.aienglish.companion.ui

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import com.aienglish.companion.AppContainer
import com.aienglish.companion.ui.nav.AppNavHost
import com.aienglish.companion.ui.nav.Routes
import com.aienglish.companion.ui.theme.AiEnglishTheme

@Composable
fun AiEnglishApp(appContainer: AppContainer) {
    CompositionLocalProvider(LocalAppContainer provides appContainer) {
        AiEnglishTheme {
            Surface(modifier = Modifier.fillMaxSize()) {
                val config by appContainer.serverConfigStore.configFlow.collectAsState(initial = null)
                config?.let { current ->
                    val startDestination = if (current.isConfigured) Routes.CharacterList else Routes.ServerSetup
                    AppNavHost(
                        serverConfigStore = appContainer.serverConfigStore,
                        startDestination = startDestination,
                    )
                }
                // config == null: first DataStore read still in flight, blank frame — acceptable
                // for this scaffolding story, no splash screen polish needed yet.
            }
        }
    }
}
