package com.aienglish.companion.ui.nav

/** Nav-graph routes. No Feedback/Review route — cut from EPIC-05 entirely,
 * see Docs/decisions/ADR-0010-epic05-scope-cuts.md. Bottom-nav tabs are
 * [Conversations], [CharacterList] and [Settings] (ADR-0015); everything
 * else is pushed on top and hides the bottom bar. */
object Routes {
    const val ServerSetup = "server_setup"
    const val Conversations = "conversations"
    const val NewConversation = "new_conversation"
    const val ConversationDetail = "conversation/{conversationId}"

    fun conversationDetail(conversationId: String): String = "conversation/$conversationId"

    /** The running conversation, full screen like a call. */
    const val VoiceSession = "voice_session"

    const val CharacterList = "character_list"

    /** Create mode. A *different* route pattern from [CharacterEditor]
     * below on purpose: when this was a bottom-nav tab, sharing one
     * pattern (distinguished only by an optional query arg) broke
     * `saveState`/`restoreState` bookkeeping — restoring could resurrect a
     * stale `characterId` from a previous edit (STORY-05-04). */
    const val CharacterCreator = "character_creator"

    /** Edit mode, pushed from the Character List's edit action. */
    const val CharacterEditor = "character_editor/{characterId}"

    fun characterEditor(characterId: String): String = "character_editor/$characterId"

    /** "How to make a great character", from the Characters tab and the creator. */
    const val CharacterGuide = "character_guide"

    const val Settings = "settings"
}
