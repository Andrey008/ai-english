package com.aienglish.companion.ui.nav

/** Nav-graph routes. No Feedback/Review route — cut from EPIC-05 entirely,
 * see Docs/decisions/ADR-0010-epic05-scope-cuts.md. */
object Routes {
    const val ServerSetup = "server_setup"
    const val CharacterList = "character_list"

    /** The bottom-nav "Create" tab — always create mode, never carries an
     * argument. Deliberately a *different* route pattern from
     * [CharacterEditor] below: giving them the same pattern (distinguished
     * only by an optional query arg) broke `saveState`/`restoreState`
     * tab-switch bookkeeping — restoring the "Create" tab's saved state
     * could resurrect a stale `characterId` from a previous edit, or vice
     * versa, since both would share one NavDestination identity. Found and
     * fixed during STORY-05-04's live verification. */
    const val CharacterCreator = "character_creator"

    /** Edit mode — a detail screen pushed on top of wherever it was opened
     * from (the Character List's edit action), not a bottom-nav tab. Plain
     * back-stack push/pop, no saveState/restoreState involved. */
    const val CharacterEditor = "character_editor/{characterId}"

    fun characterEditor(characterId: String): String = "character_editor/$characterId"

    const val VoiceSession = "voice_session"
    const val Settings = "settings"
}
