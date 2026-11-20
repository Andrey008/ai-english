package com.aienglish.companion.data.api

import com.aienglish.companion.ui.screens.wordOrigin
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Test

class VocabularyParseTest {
    private val json = Json { ignoreUnknownKeys = true }

    @Test
    fun parsesTheServerShape() {
        val body = """
            [{"id":"1","word":"crisp","context":"Do you enjoy those crisp autumn evenings?",
              "explanation":"cool and fresh","translation_ru":"прохладный","source":"asked","status":"new",
              "times_seen":2,"created_at":"a","last_seen_at":"b","session_id":"s","session_title":"Autumn walk",
              "character_name":"Emma"},
             {"id":"2","word":"lucrative","translation_ru":null,"source":"bookmark","status":"added",
              "times_seen":1,"created_at":"a","last_seen_at":"b","session_id":null,"session_title":null,
              "character_name":null}]
        """.trimIndent()
        val words = json.decodeFromString<List<VocabularyWord>>(body)
        assertEquals("прохладный", words[0].translationRu)
        assertEquals("Asked · Emma · Autumn walk · 2×", wordOrigin(words[0]))
        assertEquals("Bookmarked", wordOrigin(words[1]))
        assertEquals(VocabularyWord.STATUS_ADDED, words[1].status)
    }

    @Test
    fun clipboardTextIsOneWordPerLine() {
        val words = listOf(
            VocabularyWord(id = "1", word = "crisp", translationRu = "прохладный"),
            VocabularyWord(id = "2", word = "a piece of cake"),
        )
        assertEquals("crisp — прохладный\na piece of cake", vocabularyClipboardText(words))
    }
}
