package com.aienglish.companion.ui.screens

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Badge
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Psychology
import androidx.compose.material.icons.filled.RecordVoiceOver
import androidx.compose.material.icons.filled.School
import androidx.compose.material.icons.filled.Memory
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.aienglish.companion.ui.components.Avatar
import kotlinx.coroutines.launch

private class GuideStep(
    val title: String,
    val icon: ImageVector,
    val colors: List<Color>,
    val illustration: @Composable () -> Unit,
    val body: @Composable ColumnScope.() -> Unit,
)

/** "How to make a great character": a few swipeable illustrated steps
 * that walk through the Create character form, field by field. The
 * illustrations are drawn in Compose (mini mock-ups of the form and the
 * chat), so they follow the light/dark theme. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CharacterGuideScreen(onBack: () -> Unit, onCreate: () -> Unit) {
    val steps = guideSteps()
    val pager = rememberPagerState { steps.size }
    val scope = rememberCoroutineScope()
    val last = pager.currentPage == steps.lastIndex

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Character guide") },
                navigationIcon = {
                    IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back") }
                },
            )
        },
        bottomBar = {
            Column(modifier = Modifier.fillMaxWidth().navigationBarsPadding().padding(16.dp)) {
                PageDots(count = steps.size, current = pager.currentPage, modifier = Modifier.align(Alignment.CenterHorizontally))
                Row(modifier = Modifier.fillMaxWidth().padding(top = 16.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    if (pager.currentPage > 0) {
                        OutlinedButton(
                            onClick = { scope.launch { pager.animateScrollToPage(pager.currentPage - 1) } },
                            modifier = Modifier.weight(1f).height(52.dp),
                        ) { Text("Back") }
                    }
                    Button(
                        onClick = { if (last) onCreate() else scope.launch { pager.animateScrollToPage(pager.currentPage + 1) } },
                        modifier = Modifier.weight(1f).height(52.dp),
                    ) { Text(if (last) "Create a character" else "Next") }
                }
            }
        },
    ) { padding ->
        HorizontalPager(state = pager, modifier = Modifier.fillMaxSize().padding(padding)) { page ->
            val step = steps[page]
            Column(modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp)) {
                Hero(step)
                Text(
                    "Step ${page + 1} of ${steps.size}",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.padding(top = 20.dp),
                )
                Text(step.title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.SemiBold)
                Column(modifier = Modifier.padding(top = 12.dp, bottom = 24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    step.body(this)
                }
            }
        }
    }
}

@Composable
private fun Hero(step: GuideStep) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(220.dp)
            .clip(RoundedCornerShape(28.dp))
            .background(Brush.linearGradient(step.colors)),
        contentAlignment = Alignment.Center,
    ) {
        // Soft decorative circles behind the mock-up.
        Box(Modifier.size(180.dp).align(Alignment.TopEnd).padding(start = 60.dp, bottom = 60.dp)
            .background(Color.White.copy(alpha = 0.10f), CircleShape))
        Box(Modifier.size(120.dp).align(Alignment.BottomStart).padding(end = 40.dp, top = 40.dp)
            .background(Color.White.copy(alpha = 0.10f), CircleShape))
        Icon(
            step.icon,
            contentDescription = null,
            tint = Color.White.copy(alpha = 0.9f),
            modifier = Modifier.align(Alignment.TopStart).padding(16.dp).size(28.dp),
        )
        step.illustration()
    }
}

@Composable
private fun PageDots(count: Int, current: Int, modifier: Modifier = Modifier) {
    Row(modifier = modifier, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        repeat(count) { i ->
            val width by animateDpAsState(if (i == current) 24.dp else 8.dp, label = "dot")
            val color by animateColorAsState(
                if (i == current) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outlineVariant,
                label = "dotColor",
            )
            Box(Modifier.height(8.dp).width(width).background(color, CircleShape))
        }
    }
}

// --- Illustration building blocks: a white "card" with mock content. ---

@Composable
private fun MockCard(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Surface(
        color = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(18.dp),
        shadowElevation = 6.dp,
        modifier = modifier,
    ) { Column(modifier = Modifier.padding(14.dp), content = content) }
}

@Composable
private fun MockField(label: String, value: String) {
    Column(modifier = Modifier.padding(vertical = 3.dp)) {
        Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
        Text(value, style = MaterialTheme.typography.bodyMedium, maxLines = 2)
    }
}

@Composable
private fun MockChip(text: String, selected: Boolean) {
    Surface(
        color = if (selected) MaterialTheme.colorScheme.secondaryContainer else Color.Transparent,
        contentColor = if (selected) MaterialTheme.colorScheme.onSecondaryContainer else MaterialTheme.colorScheme.onSurfaceVariant,
        shape = RoundedCornerShape(8.dp),
        border = if (selected) null else androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp)) {
            if (selected) Icon(Icons.Default.Check, contentDescription = null, modifier = Modifier.size(14.dp).padding(end = 2.dp))
            Text(text, style = MaterialTheme.typography.labelMedium)
        }
    }
}

@Composable
private fun MockBubble(text: String, fromUser: Boolean, highlight: String? = null) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = if (fromUser) Arrangement.End else Arrangement.Start) {
        Surface(
            color = if (fromUser) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceContainerHigh,
            contentColor = if (fromUser) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurface,
            shape = RoundedCornerShape(14.dp),
            modifier = Modifier.padding(vertical = 2.dp),
        ) {
            Column(modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp)) {
                Text(text, style = MaterialTheme.typography.bodySmall)
                highlight?.let {
                    Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.secondary, fontWeight = FontWeight.SemiBold)
                }
            }
        }
    }
}

// --- Body building blocks. ---

@Composable
private fun Para(text: String) {
    Text(text, style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
}

@Composable
private fun Tip(text: String) {
    Surface(color = MaterialTheme.colorScheme.secondaryContainer, shape = RoundedCornerShape(16.dp)) {
        Row(modifier = Modifier.padding(14.dp)) {
            Icon(Icons.Default.AutoAwesome, contentDescription = null, tint = MaterialTheme.colorScheme.onSecondaryContainer, modifier = Modifier.size(20.dp))
            Text(text, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSecondaryContainer, modifier = Modifier.padding(start = 10.dp))
        }
    }
}

@Composable
private fun Example(good: Boolean, text: String) {
    val tint = if (good) Color(0xFF2E9D5B) else MaterialTheme.colorScheme.error
    Surface(
        color = MaterialTheme.colorScheme.surfaceContainerLow,
        shape = RoundedCornerShape(16.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, tint.copy(alpha = 0.5f)),
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(if (good) Icons.Default.Check else Icons.Default.Close, contentDescription = null, tint = tint, modifier = Modifier.size(18.dp))
                Text(
                    if (good) "Works well" else "Too vague",
                    style = MaterialTheme.typography.labelLarge,
                    color = tint,
                    modifier = Modifier.padding(start = 6.dp),
                )
            }
            Text("“$text”", style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 6.dp))
        }
    }
}

@Composable
private fun OptionRow(title: String, value: String, description: String) {
    Row(verticalAlignment = Alignment.Top) {
        Surface(color = MaterialTheme.colorScheme.primaryContainer, shape = RoundedCornerShape(8.dp)) {
            Text(
                value,
                style = MaterialTheme.typography.labelMedium,
                fontFamily = FontFamily.Monospace,
                color = MaterialTheme.colorScheme.onPrimaryContainer,
                modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
            )
        }
        Column(modifier = Modifier.padding(start = 12.dp)) {
            Text(title, style = MaterialTheme.typography.titleSmall)
            Text(description, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
private fun guideSteps(): List<GuideStep> = listOf(
    GuideStep(
        title = "Give them a name and a face",
        icon = Icons.Default.Badge,
        colors = listOf(Color(0xFF5C6BC0), Color(0xFF8E24AA)),
        illustration = {
            MockCard(modifier = Modifier.width(230.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Avatar("Maya", size = 44.dp)
                    Column(modifier = Modifier.padding(start = 10.dp)) {
                        Text("Maya", style = MaterialTheme.typography.titleMedium)
                        Text("maya_barista", style = MaterialTheme.typography.labelSmall, fontFamily = FontFamily.Monospace,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.padding(top = 10.dp)) {
                    MockChip("Female", true)
                    MockChip("Male", false)
                }
            }
        },
        body = {
            Para("Every character starts with who they are. The name is what you'll see in your chats, and it gets its own avatar color.")
            OptionRow("ID", "maya_barista", "A short unique slug: lowercase, no spaces. It can't be changed later.")
            OptionRow("Name", "Maya", "How the character introduces themself.")
            OptionRow("Gender", "Female", "Should match the voice you pick in step 3.")
            Tip("Make a few different characters for different moods — a friend for small talk, a coach for interviews, a teacher for grammar.")
        },
    ),
    GuideStep(
        title = "Describe their role",
        icon = Icons.Default.Psychology,
        colors = listOf(Color(0xFF00897B), Color(0xFF26A69A)),
        illustration = {
            MockCard(modifier = Modifier.width(260.dp)) {
                MockField("Role description", "A cheerful barista in London who loves indie music. Chats casually, asks about your day…")
                Spacer(Modifier.height(6.dp))
                Box(Modifier.fillMaxWidth().height(6.dp).background(MaterialTheme.colorScheme.surfaceContainerHigh, CircleShape))
                Spacer(Modifier.height(4.dp))
                Box(Modifier.fillMaxWidth(0.7f).height(6.dp).background(MaterialTheme.colorScheme.surfaceContainerHigh, CircleShape))
            }
        },
        body = {
            Para("This is the most important field. The character reads it before every conversation, so it decides how they talk, what they talk about and how they treat you.")
            Para("Write 2–5 sentences, in English, saying:")
            OptionRow("Who", "1", "Their job, age, where they live, a hobby or two.")
            OptionRow("How", "2", "Their manner: warm, witty, calm, direct, curious.")
            OptionRow("What", "3", "What a conversation with them is for: chatting, practising interviews, ordering in a café.")
            Example(
                good = true,
                text = "A cheerful barista in London who loves indie music and dogs. Chats casually about everyday life, asks about your day and shares small stories from the café. Uses common British expressions and explains them if you ask.",
            )
            Example(good = false, text = "A friendly person who speaks English.")
            Tip("You don't need to explain how to be a conversation partner or how long replies should be — the app already tells every character that.")
        },
    ),
    GuideStep(
        title = "Pick a voice",
        icon = Icons.Default.RecordVoiceOver,
        colors = listOf(Color(0xFFEF6C00), Color(0xFFFFA726)),
        illustration = {
            MockCard(modifier = Modifier.width(250.dp)) {
                MockField("TTS voice ID", "en_GB-alan-medium")
                Row(horizontalArrangement = Arrangement.spacedBy(3.dp), verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.padding(top = 10.dp)) {
                    listOf(10, 22, 14, 30, 18, 26, 12, 24, 16, 28, 10, 20, 14).forEach { h ->
                        Box(Modifier.width(6.dp).height(h.dp).background(MaterialTheme.colorScheme.primary, CircleShape))
                    }
                }
            }
        },
        body = {
            Para("Type one of the voices installed on your server into “TTS voice ID”, and set “Accent” to match:")
            OptionRow("Amy · American", "en_US-amy-medium", "Female, friendly and clear. Accent: en_US.")
            OptionRow("Lessac · American", "en_US-lessac-medium", "Female, calm and neutral. Accent: en_US.")
            OptionRow("Alan · British", "en_GB-alan-medium", "Male, relaxed British English. Accent: en_GB.")
            Para("Leave the TTS engine on Piper — it's fast enough for a live conversation.")
            Tip("Practising for a trip or a job abroad? Choose the accent you'll actually hear there.")
        },
    ),
    GuideStep(
        title = "Choose how they correct you",
        icon = Icons.Default.School,
        colors = listOf(Color(0xFFC2185B), Color(0xFFEC407A)),
        illustration = {
            MockCard(modifier = Modifier.width(260.dp)) {
                MockBubble("Yesterday I go to the cinema.", fromUser = true)
                MockBubble("Oh nice, you went to the cinema! What did you see?", fromUser = false, highlight = "went ✓")
            }
        },
        body = {
            OptionRow("Off", "off", "Pure conversation, no corrections. Best for building confidence and fluency.")
            OptionRow("Live gentle", "live_gentle", "When you make a clear mistake, they naturally say it the right way in their reply — at most one small fix at a time.")
            OptionRow("End of session", "end_of_session", "No corrections while you talk. (A feedback summary at the end isn't built yet — for now it works like Off.)")
            Tip("Live gentle is the most useful for learning: you hear the correct version right away, without the conversation stopping.")
        },
    ),
    GuideStep(
        title = "Decide what they remember",
        icon = Icons.Default.Memory,
        colors = listOf(Color(0xFF3949AB), Color(0xFF42A5F5)),
        illustration = {
            MockCard(modifier = Modifier.width(250.dp)) {
                Text("Maya remembers", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
                listOf("Your name is Andrew", "Works in software", "Loves basketball").forEach { fact ->
                    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 6.dp)) {
                        Icon(Icons.Default.Check, contentDescription = null, tint = Color(0xFF2E9D5B), modifier = Modifier.size(16.dp))
                        Text(fact, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(start = 6.dp))
                    }
                }
                Spacer(Modifier.height(10.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("Memory enabled", style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                    Box(Modifier.width(36.dp).height(20.dp).background(MaterialTheme.colorScheme.primary, CircleShape),
                        contentAlignment = Alignment.CenterEnd) {
                        Box(Modifier.padding(3.dp).size(14.dp).background(Color.White, CircleShape))
                    }
                }
            }
        },
        body = {
            OptionRow("Memory", "on", "The character remembers facts about you between conversations — your name, job, hobbies, plans — and brings them up naturally.")
            OptionRow("Memory", "off", "Every conversation starts from scratch. Good for role-play like a job interview with a stranger.")
            Para("You can wipe what a character remembers at any time: open the character and tap “Reset memory”. Or start a single conversation without it — the switch is on the New conversation screen.")
            OptionRow("Temperature", "0.7", "Saved with the character, but the server doesn't use it yet — leave it as it is.")
        },
    ),
    GuideStep(
        title = "Start talking",
        icon = Icons.Default.AutoAwesome,
        colors = listOf(Color(0xFF2E7D32), Color(0xFF66BB6A)),
        illustration = {
            MockCard(modifier = Modifier.width(250.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(bottom = 8.dp)) {
                    Avatar("Maya", size = 32.dp)
                    Text("Maya", style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(start = 8.dp))
                }
                MockBubble("Hiya! What can I get you today?", fromUser = false)
                MockBubble("A flat white, please!", fromUser = true)
            }
        },
        body = {
            Para("Tap Create — your character appears on the Characters tab. Then go to Conversations, tap New conversation, pick them and start talking.")
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("Characters", "＋ Create", "Conversations", "New conversation", "Start").forEachIndexed { i, label ->
                    MockChip(if (i == 0) label else "→ $label", selected = i == 4)
                }
            }
            Tip("Not quite right? Edit the role description and try again — small changes in it change the character a lot.")
        },
    ),
)
