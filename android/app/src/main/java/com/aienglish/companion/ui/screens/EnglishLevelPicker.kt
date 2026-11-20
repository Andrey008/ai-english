package com.aienglish.companion.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.aienglish.companion.data.EnglishLevel

/** Shared by Settings (the default) and the session start screen (this
 * session only). */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun EnglishLevelPicker(
    selected: EnglishLevel,
    onSelect: (EnglishLevel) -> Unit,
    modifier: Modifier = Modifier,
) {
    FlowRow(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        EnglishLevel.entries.forEach { level ->
            FilterChip(
                selected = level == selected,
                onClick = { onSelect(level) },
                label = { Text(level.label) },
            )
        }
    }
}
