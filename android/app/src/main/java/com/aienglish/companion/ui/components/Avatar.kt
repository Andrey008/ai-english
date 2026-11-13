package com.aienglish.companion.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

// Soft, distinct hues that read on both light and dark backgrounds with
// white initials.
private val AvatarColors = listOf(
    Color(0xFF5C6BC0), Color(0xFF26A69A), Color(0xFFEC407A), Color(0xFFFFA726),
    Color(0xFF7E57C2), Color(0xFF42A5F5), Color(0xFF66BB6A), Color(0xFF8D6E63),
)

/** A stable color per character, so Emma looks the same everywhere. */
fun avatarColor(key: String?): Color =
    if (key.isNullOrEmpty()) Color(0xFF90A4AE) else AvatarColors[Math.floorMod(key.hashCode(), AvatarColors.size)]

/** A character's initial on its color. [key] is what picks the color
 * (the character id, or the name when there's no id). */
@Composable
fun Avatar(name: String?, key: String? = name, size: Dp = 44.dp, modifier: Modifier = Modifier) {
    Box(
        modifier = modifier.size(size).background(avatarColor(key), CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            name?.trim()?.take(1)?.uppercase() ?: "?",
            color = Color.White,
            fontWeight = FontWeight.SemiBold,
            fontSize = (size.value * 0.42f).sp,
        )
    }
}

/** Section heading used across screens. */
@Composable
fun SectionHeader(text: String, modifier: Modifier = Modifier) {
    Text(
        text.uppercase(),
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.primary,
        fontWeight = FontWeight.SemiBold,
        letterSpacing = 1.sp,
        modifier = modifier,
    )
}
