package com.aienglish.companion.data.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** Mirrors `server/app/presets.py`'s `CharacterPreset` field-for-field
 * (`ADR-0008` — structured persona fields, not an opaque prompt blob). */
@Serializable
data class CharacterPreset(
    val id: String,
    val name: String,
    val gender: Gender,
    val accent: String = "en_US",
    @SerialName("avatar_path") val avatarPath: String = "",
    @SerialName("role_description") val roleDescription: String,
    @SerialName("system_prompt_override") val systemPromptOverride: String? = null,
    @SerialName("tts_voice_id") val ttsVoiceId: String,
    @SerialName("tts_engine") val ttsEngine: TtsEngine = TtsEngine.PIPER,
    @SerialName("voice_reference_path") val voiceReferencePath: String? = null,
    val temperature: Double = 0.7,
    @SerialName("correction_style") val correctionStyle: CorrectionStyle = CorrectionStyle.OFF,
    @SerialName("memory_enabled") val memoryEnabled: Boolean = true,
)

@Serializable
enum class Gender {
    @SerialName("male") MALE,
    @SerialName("female") FEMALE,
}

@Serializable
enum class TtsEngine {
    @SerialName("piper") PIPER,
    @SerialName("xtts") XTTS,
}

@Serializable
enum class CorrectionStyle {
    @SerialName("off") OFF,
    @SerialName("end_of_session") END_OF_SESSION,
    @SerialName("live_gentle") LIVE_GENTLE,
}
