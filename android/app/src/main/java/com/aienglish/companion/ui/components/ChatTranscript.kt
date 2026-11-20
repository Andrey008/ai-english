package com.aienglish.companion.ui.components

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.unit.dp
import com.aienglish.companion.data.ws.TranscriptEntry

/** What the character is doing at the bottom of the chat: a "typing"
 * bubble while it thinks, nothing otherwise. */
enum class ChatActivity { NONE, THINKING }

/** Messenger-style transcript: the user's lines on the right in the
 * primary color, the character's on the left with its avatar and name
 * on the first line of a run. Scrolls to the newest message. */
@Composable
fun ChatTranscript(
    transcript: List<TranscriptEntry>,
    characterName: String,
    characterKey: String?,
    listState: LazyListState,
    modifier: Modifier = Modifier,
    activity: ChatActivity = ChatActivity.NONE,
    contentPadding: PaddingValues = PaddingValues(horizontal = 12.dp, vertical = 12.dp),
) {
    val itemCount = transcript.size + if (activity == ChatActivity.THINKING) 1 else 0
    LaunchedEffect(itemCount) {
        if (itemCount > 0) listState.animateScrollToItem(itemCount - 1)
    }
    LazyColumn(
        state = listState,
        modifier = modifier.fillMaxWidth(),
        contentPadding = contentPadding,
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        itemsIndexed(transcript) { index, entry ->
            val previous = transcript.getOrNull(index - 1)
            val firstOfRun = previous == null || previous::class != entry::class
            if (firstOfRun && index > 0) Spacer(Modifier.size(8.dp))
            when (entry) {
                is TranscriptEntry.User -> UserBubble(entry.text)
                is TranscriptEntry.Character -> CharacterBubble(entry.text, characterName, characterKey, firstOfRun)
            }
        }
        if (activity == ChatActivity.THINKING) {
            item {
                val lastIsCharacter = transcript.lastOrNull() is TranscriptEntry.Character
                if (!lastIsCharacter) Spacer(Modifier.size(8.dp))
                CharacterRow(characterName, characterKey, showHeader = !lastIsCharacter) { TypingDots() }
            }
        }
    }
}

private val UserShape = RoundedCornerShape(20.dp, 20.dp, 6.dp, 20.dp)
private val CharacterShape = RoundedCornerShape(20.dp, 20.dp, 20.dp, 6.dp)

@Composable
private fun UserBubble(text: String) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
        Surface(
            color = MaterialTheme.colorScheme.primary,
            contentColor = MaterialTheme.colorScheme.onPrimary,
            shape = UserShape,
            modifier = Modifier.padding(start = 56.dp).widthIn(max = 320.dp),
        ) {
            Text(text, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp))
        }
    }
}

@Composable
private fun CharacterBubble(text: String, name: String, key: String?, showHeader: Boolean) {
    CharacterRow(name, key, showHeader) {
        Text(text, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp))
    }
}

@Composable
private fun CharacterRow(name: String, key: String?, showHeader: Boolean, content: @Composable () -> Unit) {
    Row(modifier = Modifier.fillMaxWidth().padding(end = 48.dp), verticalAlignment = Alignment.Bottom) {
        Box(modifier = Modifier.size(32.dp)) {
            if (showHeader) Avatar(name, key, size = 32.dp)
        }
        Column(modifier = Modifier.padding(start = 8.dp)) {
            if (showHeader) {
                Text(
                    name,
                    style = MaterialTheme.typography.labelMedium,
                    color = avatarColor(key),
                    modifier = Modifier.padding(start = 4.dp, bottom = 2.dp),
                )
            }
            Surface(
                color = MaterialTheme.colorScheme.surfaceContainerHigh,
                contentColor = MaterialTheme.colorScheme.onSurface,
                shape = CharacterShape,
                modifier = Modifier.widthIn(max = 320.dp),
            ) { content() }
        }
    }
}

@Composable
private fun TypingDots() {
    val transition = rememberInfiniteTransition(label = "typing")
    Row(
        modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp),
        horizontalArrangement = Arrangement.spacedBy(5.dp),
    ) {
        repeat(3) { i ->
            val alpha by transition.animateFloat(
                initialValue = 0.25f,
                targetValue = 1f,
                animationSpec = infiniteRepeatable(tween(500, delayMillis = i * 160), RepeatMode.Reverse),
                label = "dot$i",
            )
            Box(
                Modifier.size(8.dp).alpha(alpha)
                    .background(MaterialTheme.colorScheme.onSurfaceVariant, CircleShape),
            )
        }
    }
}
