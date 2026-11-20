package com.aienglish.companion.data.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** One word from `GET /vocabulary` (AE-5): something the user asked about
 * or bookmarked in a conversation, collected to be added to EnglishDom by
 * hand. [status]: `new` | `added` (already in EnglishDom) | `dismissed`. */
@Serializable
data class VocabularyWord(
    val id: String,
    val word: String,
    val context: String? = null,
    val explanation: String? = null,
    @SerialName("translation_ru") val translationRu: String? = null,
    /** `asked` | `bookmark`. */
    val source: String = "asked",
    val status: String = STATUS_NEW,
    @SerialName("times_seen") val timesSeen: Int = 1,
    @SerialName("created_at") val createdAt: String = "",
    @SerialName("last_seen_at") val lastSeenAt: String = "",
    @SerialName("session_id") val sessionId: String? = null,
    @SerialName("session_title") val sessionTitle: String? = null,
    @SerialName("character_name") val characterName: String? = null,
) {
    companion object {
        const val STATUS_NEW = "new"
        const val STATUS_ADDED = "added"
        const val STATUS_DISMISSED = "dismissed"
    }
}

@Serializable
data class VocabularyStatus(val status: String)

@Serializable
data class VocabularyBulkStatus(val ids: List<String>, val status: String)

/** Plain text for pasting into EnglishDom (or a note): one word per line,
 * "word — перевод", so the translation can be checked while adding. */
fun vocabularyClipboardText(words: List<VocabularyWord>): String =
    words.joinToString("\n") { w ->
        val ru = w.translationRu?.takeIf { it.isNotBlank() }
        if (ru != null) "${w.word} — $ru" else w.word
    }
