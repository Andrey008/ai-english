package com.aienglish.companion.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/** How simply characters speak — sent as `english_level` in
 * `session_start`; ids match the server's `persona.ENGLISH_LEVELS`. */
enum class EnglishLevel(val id: String, val label: String) {
    A2("A2", "A2 Elementary"),
    B1("B1", "B1 Intermediate"),
    B2("B2", "B2 Upper-Int."),
    C1("C1", "C1 Advanced"),
    NATIVE("native", "Native");

    companion object {
        val DEFAULT = B1
        fun fromId(id: String?): EnglishLevel = entries.firstOrNull { it.id == id } ?: DEFAULT
    }
}

private val Context.englishLevelDataStore: DataStore<Preferences> by preferencesDataStore(
    name = "english_level"
)

/** The default level preselected on the session start screen — each
 * session can still pick a different one without changing this. */
class EnglishLevelStore(private val context: Context) {
    private val keyDefaultLevel = stringPreferencesKey("default_level")

    val defaultLevelFlow: Flow<EnglishLevel> = context.englishLevelDataStore.data.map { prefs ->
        EnglishLevel.fromId(prefs[keyDefaultLevel])
    }

    suspend fun setDefault(level: EnglishLevel) {
        context.englishLevelDataStore.edit { prefs -> prefs[keyDefaultLevel] = level.id }
    }
}
