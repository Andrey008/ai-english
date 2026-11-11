package com.aienglish.companion.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.audioPrefsDataStore: DataStore<Preferences> by preferencesDataStore(
    name = "audio_prefs"
)

/** Remembered audio choices from the session start screen. By default a
 * connected Bluetooth headset's mic records, as Android does in calls;
 * the phone mic is used only when forced here. */
class AudioPrefsStore(private val context: Context) {
    private val keyForcePhoneMic = booleanPreferencesKey("force_phone_mic")

    val forcePhoneMicFlow: Flow<Boolean> = context.audioPrefsDataStore.data.map { prefs ->
        prefs[keyForcePhoneMic] ?: false
    }

    suspend fun setForcePhoneMic(enabled: Boolean) {
        context.audioPrefsDataStore.edit { prefs -> prefs[keyForcePhoneMic] = enabled }
    }
}
