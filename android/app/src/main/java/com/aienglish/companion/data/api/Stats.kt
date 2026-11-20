package com.aienglish.companion.data.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** `GET /stats` (`server/app/stats.py`): how much the user practiced. All
 * durations are whole seconds. */
@Serializable
data class PracticeStats(
    val timezone: String = "",
    @SerialName("first_day") val firstDay: String? = null,
    val totals: StatsBucket = StatsBucket(),
    val today: StatsBucket = StatsBucket(),
    @SerialName("last_7_days") val last7Days: StatsBucket = StatsBucket(),
    @SerialName("last_30_days") val last30Days: StatsBucket = StatsBucket(),
    val streak: Streak = Streak(),
    val daily: List<DailyStats> = emptyList(),
    @SerialName("by_character") val byCharacter: List<CharacterStats> = emptyList(),
    @SerialName("by_kind") val byKind: Map<String, StatsBucket> = emptyMap(),
)

@Serializable
data class StatsBucket(
    val sessions: Int = 0,
    @SerialName("user_turns") val userTurns: Int = 0,
    @SerialName("user_words") val userWords: Int = 0,
    @SerialName("practice_s") val practiceS: Long = 0,
    @SerialName("speaking_s") val speakingS: Long = 0,
    @SerialName("listening_s") val listeningS: Long = 0,
    @SerialName("estimated_audio_s") val estimatedAudioS: Long = 0,
    @SerialName("avg_words_per_turn") val avgWordsPerTurn: Double? = null,
    @SerialName("words_per_minute") val wordsPerMinute: Double? = null,
)

@Serializable
data class Streak(
    @SerialName("current_days") val currentDays: Int = 0,
    @SerialName("longest_days") val longestDays: Int = 0,
    @SerialName("practiced_today") val practicedToday: Boolean = false,
)

@Serializable
data class DailyStats(
    val date: String,
    @SerialName("practice_s") val practiceS: Long = 0,
    @SerialName("speaking_s") val speakingS: Long = 0,
    @SerialName("user_words") val userWords: Int = 0,
    val sessions: Int = 0,
)

@Serializable
data class CharacterStats(
    @SerialName("character_id") val characterId: String? = null,
    val name: String? = null,
    val sessions: Int = 0,
    @SerialName("user_words") val userWords: Int = 0,
    @SerialName("practice_s") val practiceS: Long = 0,
    @SerialName("speaking_s") val speakingS: Long = 0,
)
