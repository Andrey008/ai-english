package com.aienglish.companion.data.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** Mirrors `server/app/scenarios.py`'s `ScenarioDefinition` field-for-field. */
@Serializable
data class ScenarioDefinition(
    val id: String,
    val title: String,
    val difficulty: Int,
    @SerialName("character_role_prompt_addendum") val characterRolePromptAddendum: String,
    val goal: String,
    @SerialName("opening_line_hint") val openingLineHint: String,
)
