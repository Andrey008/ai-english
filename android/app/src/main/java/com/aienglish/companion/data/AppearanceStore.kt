package com.aienglish.companion.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

enum class ThemeMode(val label: String) { SYSTEM("System"), LIGHT("Light"), DARK("Dark") }

data class Appearance(val themeMode: ThemeMode = ThemeMode.SYSTEM, val wallpaperColors: Boolean = false)

private val Context.appearanceDataStore: DataStore<Preferences> by preferencesDataStore(name = "appearance")

/** Light/dark theme choice and whether to take colors from the wallpaper
 * (Material You) instead of the app's own palette. Set in Settings. */
class AppearanceStore(private val context: Context) {
    private val keyThemeMode = stringPreferencesKey("theme_mode")
    private val keyWallpaperColors = booleanPreferencesKey("wallpaper_colors")

    val appearanceFlow: Flow<Appearance> = context.appearanceDataStore.data.map { prefs ->
        Appearance(
            themeMode = ThemeMode.entries.firstOrNull { it.name == prefs[keyThemeMode] } ?: ThemeMode.SYSTEM,
            wallpaperColors = prefs[keyWallpaperColors] ?: false,
        )
    }

    suspend fun setThemeMode(mode: ThemeMode) {
        context.appearanceDataStore.edit { it[keyThemeMode] = mode.name }
    }

    suspend fun setWallpaperColors(enabled: Boolean) {
        context.appearanceDataStore.edit { it[keyWallpaperColors] = enabled }
    }
}
