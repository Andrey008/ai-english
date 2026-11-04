package com.aienglish.companion.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/** Which character a new Voice Session uses by default — local-only,
 * doesn't exist server-side (STORY-05-03). */
private val Context.characterSelectionDataStore: DataStore<Preferences> by preferencesDataStore(
    name = "character_selection"
)

class CharacterSelectionStore(private val context: Context) {
    private val keySelectedId = stringPreferencesKey("selected_character_id")

    val selectedIdFlow: Flow<String?> = context.characterSelectionDataStore.data.map { prefs ->
        prefs[keySelectedId]
    }

    suspend fun select(characterId: String) {
        context.characterSelectionDataStore.edit { prefs -> prefs[keySelectedId] = characterId }
    }

    suspend fun clear() {
        context.characterSelectionDataStore.edit { prefs -> prefs.remove(keySelectedId) }
    }
}
