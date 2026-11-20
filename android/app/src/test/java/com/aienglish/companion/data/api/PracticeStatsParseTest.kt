package com.aienglish.companion.data.api

import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Test

class PracticeStatsParseTest {
    @Test
    fun parsesTheServerShape() {
        val body = """
            {"timezone":"Europe/Kyiv","generated_at":"x","first_day":"2026-11-01",
             "totals":{"sessions":3,"user_turns":10,"user_words":120,"practice_s":900,"speaking_s":300,
                       "listening_s":400,"estimated_audio_s":50,"avg_words_per_turn":12.0,"words_per_minute":null},
             "today":{"sessions":0,"user_turns":0,"user_words":0,"practice_s":0,"speaking_s":0,"listening_s":0,
                      "estimated_audio_s":0,"avg_words_per_turn":null,"words_per_minute":null},
             "streak":{"current_days":2,"longest_days":4,"practiced_today":false},
             "daily":[{"date":"2026-11-19","practice_s":60,"speaking_s":20,"user_words":30,"sessions":1}],
             "by_character":[{"character_id":"emma_teacher","name":"Emma","sessions":2,"practice_s":600}],
             "by_kind":{"free":{"practice_s":900}}}
        """.trimIndent()
        val stats = Json { ignoreUnknownKeys = true }.decodeFromString<PracticeStats>(body)
        assertEquals(900L, stats.totals.practiceS)
        assertEquals(2, stats.streak.currentDays)
        assertEquals("Emma", stats.byCharacter.single().name)
        assertEquals(900L, stats.byKind["free"]?.practiceS)
        assertEquals(0L, stats.last7Days.practiceS) // missing → default
    }
}
