package com.aienglish.companion.ui

import androidx.compose.runtime.staticCompositionLocalOf
import com.aienglish.companion.AppContainer

val LocalAppContainer = staticCompositionLocalOf<AppContainer> {
    error("AppContainer not provided — wrap the tree in CompositionLocalProvider")
}
