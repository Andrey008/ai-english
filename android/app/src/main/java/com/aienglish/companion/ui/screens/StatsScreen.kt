package com.aienglish.companion.ui.screens

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.LocalFireDepartment
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LargeTopAppBar
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.aienglish.companion.data.api.ApiResult
import com.aienglish.companion.data.api.DailyStats
import com.aienglish.companion.data.api.PracticeStats
import com.aienglish.companion.data.api.StatsBucket
import com.aienglish.companion.ui.LocalAppContainer
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.format.TextStyle
import java.util.Locale

/** "1h 05m", "12m", "45s", "0m". */
internal fun formatDuration(seconds: Long): String {
    if (seconds <= 0) return "0m"
    val h = seconds / 3600
    val m = (seconds % 3600) / 60
    return when {
        h > 0 -> "${h}h %02dm".format(m)
        m > 0 -> "${m}m"
        else -> "${seconds}s"
    }
}

private enum class Period(val label: String, val days: Int) { WEEK("7 days", 7), MONTH("30 days", 30) }

/** How much the user practiced (`GET /stats`): today, the streak, the
 * chosen period, minutes per day and the split by character. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun StatsScreen() {
    val appContainer = LocalAppContainer.current
    val scope = rememberCoroutineScope()
    var stats by remember { mutableStateOf<PracticeStats?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(false) }
    var period by remember { mutableStateOf(Period.WEEK) }

    suspend fun refresh() {
        loading = true
        error = null
        when (val result = appContainer.apiClient.stats(days = 30)) {
            is ApiResult.Success -> stats = result.data
            is ApiResult.HttpError -> error = "Server error ${result.code}" +
                if (result.code == 404) " — the server is older than this app, restart it." else ""
            is ApiResult.NetworkError -> error = "Can't reach the server — check Settings for the host/port."
        }
        loading = false
    }

    LaunchedEffect(Unit) { refresh() }

    Scaffold(
        topBar = {
            LargeTopAppBar(
                title = { Text("Stats") },
                actions = {
                    IconButton(onClick = { scope.launch { refresh() } }, enabled = !loading) {
                        Icon(Icons.Default.Refresh, contentDescription = "Refresh")
                    }
                },
            )
        },
    ) { padding ->
        val current = stats
        when {
            current == null && error != null -> Column(
                Modifier.fillMaxSize().padding(padding).padding(24.dp),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(error.orEmpty(), textAlign = TextAlign.Center)
                Button(onClick = { scope.launch { refresh() } }, modifier = Modifier.padding(top = 16.dp)) { Text("Retry") }
            }
            current == null -> Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
            else -> StatsContent(
                stats = current,
                period = period,
                onPeriod = { period = it },
                modifier = Modifier.padding(padding),
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun StatsContent(
    stats: PracticeStats,
    period: Period,
    onPeriod: (Period) -> Unit,
    modifier: Modifier = Modifier,
) {
    val bucket = if (period == Period.WEEK) stats.last7Days else stats.last30Days
    Column(
        modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Tile("Today", formatDuration(stats.today.practiceS),
                "${stats.today.userWords} words spoken", Modifier.weight(1f))
            StreakTile(stats, Modifier.weight(1f))
        }

        SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
            Period.entries.forEachIndexed { i, p ->
                SegmentedButton(
                    selected = p == period,
                    onClick = { onPeriod(p) },
                    shape = SegmentedButtonDefaults.itemShape(i, Period.entries.size),
                ) { Text(p.label) }
            }
        }

        SectionCard("Practice time") {
            Text(formatDuration(bucket.practiceS), style = MaterialTheme.typography.displaySmall)
            Text(
                "${bucket.sessions} conversation${if (bucket.sessions == 1) "" else "s"} · " +
                    "total ${formatDuration(stats.totals.practiceS)} since ${stats.firstDay ?: "—"}",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(16.dp))
            DailyChart(stats.daily.takeLast(period.days))
        }

        SectionCard("You") { BucketDetails(bucket) }

        if (stats.byCharacter.isNotEmpty()) {
            SectionCard("By character · all time") {
                val max = stats.byCharacter.maxOf { it.practiceS }.coerceAtLeast(1)
                stats.byCharacter.forEach { c ->
                    ShareRow(
                        label = c.name ?: c.characterId ?: "Unknown",
                        value = "${formatDuration(c.practiceS)} · ${c.sessions}",
                        fraction = c.practiceS.toFloat() / max,
                    )
                }
            }
        }

        val kinds = listOf("free" to "Free talk", "scenario" to "Scenarios", "interview" to "Interview prep")
            .mapNotNull { (key, label) -> stats.byKind[key]?.let { label to it } }
            .filter { it.second.practiceS > 0 }
        if (kinds.size > 1) {
            SectionCard("By kind · all time") {
                val max = kinds.maxOf { it.second.practiceS }.coerceAtLeast(1)
                kinds.forEach { (label, b) ->
                    ShareRow(label, formatDuration(b.practiceS), b.practiceS.toFloat() / max)
                }
            }
        }

        if (stats.totals.estimatedAudioS > 0) {
            Text(
                "Speaking and listening time for older conversations is estimated from word counts.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun Tile(title: String, value: String, subtitle: String, modifier: Modifier = Modifier) {
    Card(modifier) {
        Column(Modifier.padding(16.dp)) {
            Text(title, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(value, style = MaterialTheme.typography.headlineMedium)
            Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun StreakTile(stats: PracticeStats, modifier: Modifier = Modifier) {
    val streak = stats.streak
    val active = streak.currentDays > 0
    Card(
        modifier,
        colors = if (active) CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.tertiaryContainer)
        else CardDefaults.cardColors(),
    ) {
        Column(Modifier.padding(16.dp)) {
            Text("Streak", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (active) {
                    Icon(Icons.Default.LocalFireDepartment, contentDescription = null,
                        tint = MaterialTheme.colorScheme.tertiary, modifier = Modifier.padding(end = 4.dp))
                }
                Text("${streak.currentDays} day${if (streak.currentDays == 1) "" else "s"}",
                    style = MaterialTheme.typography.headlineMedium)
            }
            Text(
                when {
                    active && !streak.practicedToday -> "Talk today to keep it"
                    else -> "Longest: ${streak.longestDays}"
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun SectionCard(title: String, content: @Composable () -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(bottom = 8.dp))
            content()
        }
    }
}

@Composable
private fun BucketDetails(b: StatsBucket) {
    Detail("Speaking", formatDuration(b.speakingS))
    Detail("Listening", formatDuration(b.listeningS))
    Detail("Words spoken", "%,d".format(b.userWords))
    b.avgWordsPerTurn?.let { Detail("Words per reply", "%.1f".format(it)) }
    b.wordsPerMinute?.let { Detail("Speaking pace", "%.0f words/min".format(it)) }
}

@Composable
private fun Detail(label: String, value: String) {
    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Text(label, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
        Text(value, style = MaterialTheme.typography.bodyLarge)
    }
}

@Composable
private fun ShareRow(label: String, value: String, fraction: Float) {
    Column(Modifier.padding(vertical = 6.dp)) {
        Row(Modifier.fillMaxWidth()) {
            Text(label, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f),
                maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(value, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Box(
            Modifier.padding(top = 4.dp).fillMaxWidth().height(6.dp)
                .background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(3.dp))
        ) {
            Box(
                Modifier.fillMaxWidth(fraction.coerceIn(0.02f, 1f)).height(6.dp)
                    .background(MaterialTheme.colorScheme.primary, RoundedCornerShape(3.dp))
            )
        }
    }
}

/** Minutes per day; today is the last bar. */
@Composable
private fun DailyChart(days: List<DailyStats>) {
    if (days.isEmpty()) return
    val maxS = days.maxOf { it.practiceS }.coerceAtLeast(60)
    val barColor = MaterialTheme.colorScheme.primary
    val emptyColor = MaterialTheme.colorScheme.surfaceVariant
    Text(
        "Best day: ${formatDuration(days.maxOf { it.practiceS })}",
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    Canvas(Modifier.fillMaxWidth().height(120.dp).padding(top = 8.dp)) {
        val slot = size.width / days.size
        val barW = slot * 0.62f
        days.forEachIndexed { i, d ->
            val h = if (d.practiceS > 0) (d.practiceS.toFloat() / maxS * size.height).coerceAtLeast(4f) else 4f
            drawRoundRect(
                color = if (d.practiceS > 0) barColor else emptyColor,
                topLeft = Offset(i * slot + (slot - barW) / 2, size.height - h),
                size = Size(barW, h),
                cornerRadius = CornerRadius(barW / 4),
            )
        }
    }
    // Labels: every day for a week, about weekly for a month.
    val step = if (days.size <= 7) 1 else 7
    Row(Modifier.fillMaxWidth().padding(top = 4.dp)) {
        days.forEachIndexed { i, d ->
            val fromEnd = days.size - 1 - i
            val label = if (fromEnd % step == 0) dayLabel(d.date, days.size <= 7) else ""
            Text(label, style = MaterialTheme.typography.labelSmall, textAlign = TextAlign.Center,
                maxLines = 1, softWrap = false, modifier = Modifier.weight(1f).width(0.dp))
        }
    }
}

private fun dayLabel(iso: String, weekday: Boolean): String = runCatching {
    val d = LocalDate.parse(iso)
    if (weekday) d.dayOfWeek.getDisplayName(TextStyle.SHORT, Locale.ENGLISH) else "${d.dayOfMonth}/${d.monthValue}"
}.getOrDefault("")
