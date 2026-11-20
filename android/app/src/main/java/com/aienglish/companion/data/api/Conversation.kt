package com.aienglish.companion.data.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** One `/conversations` item (`server/app/main.py`'s
 * `conversation_summary`, ADR-0015). `title` is the server's wrap-up
 * after a clean end; older conversations only have `topic`, their first
 * user line. */
@Serializable
data class ConversationSummary(
    val id: String,
    @SerialName("character_id") val characterId: String? = null,
    @SerialName("character_name") val characterName: String? = null,
    @SerialName("scenario_id") val scenarioId: String? = null,
    @SerialName("english_level") val englishLevel: String? = null,
    val title: String? = null,
    val topic: String? = null,
    @SerialName("started_at") val startedAt: String,
    @SerialName("last_turn_at") val lastTurnAt: String? = null,
    val turns: Int = 0,
    @SerialName("user_turns") val userTurns: Int = 0,
    val active: Boolean = false,
    @SerialName("can_resume") val canResume: Boolean = true,
) {
    val displayTitle: String get() = title ?: topic ?: "Conversation"
}

@Serializable
data class TranscriptTurn(val role: String, val text: String, val ts: String)

@Serializable
data class ConversationDetail(
    val id: String,
    @SerialName("character_id") val characterId: String? = null,
    @SerialName("character_name") val characterName: String? = null,
    @SerialName("scenario_id") val scenarioId: String? = null,
    @SerialName("english_level") val englishLevel: String? = null,
    val title: String? = null,
    val topic: String? = null,
    @SerialName("started_at") val startedAt: String,
    @SerialName("last_turn_at") val lastTurnAt: String? = null,
    val active: Boolean = false,
    @SerialName("can_resume") val canResume: Boolean = true,
    val transcript: List<TranscriptTurn> = emptyList(),
) {
    val displayTitle: String get() = title ?: topic ?: "Conversation"
}

@Serializable
data class ConversationRename(val title: String)
