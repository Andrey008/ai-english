package com.aienglish.companion.data.ws

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

sealed class TranscriptEntry {
    abstract val text: String

    data class User(override val text: String) : TranscriptEntry()
    data class Character(override val text: String) : TranscriptEntry()
}

/** The current conversation's transcript, kept for the app's lifetime
 * rather than in the session screen's state, so leaving that screen and
 * coming back (the session keeps running in the foreground service)
 * doesn't lose it. Character sentences arrive one per
 * `response_text_chunk`; they're joined into one entry per reply. */
class LiveTranscript(wsSessionClient: WsSessionClient) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val _entries = MutableStateFlow<List<TranscriptEntry>>(emptyList())
    val entries: StateFlow<List<TranscriptEntry>> = _entries.asStateFlow()

    init {
        scope.launch {
            wsSessionClient.events.collect { event ->
                when (event) {
                    is WsEvent.TranscriptFinal -> _entries.update { it + TranscriptEntry.User(event.text) }
                    is WsEvent.ResponseTextChunk -> _entries.update { entries ->
                        val last = entries.lastOrNull()
                        if (event.sentenceIndex > 0 && last is TranscriptEntry.Character) {
                            entries.dropLast(1) + TranscriptEntry.Character("${last.text} ${event.text}")
                        } else {
                            entries + TranscriptEntry.Character(event.text)
                        }
                    }
                    else -> Unit
                }
            }
        }
    }

    /** A new conversation starts empty; a continued one with its past turns. */
    fun reset(initial: List<TranscriptEntry> = emptyList()) {
        _entries.value = initial
    }
}
