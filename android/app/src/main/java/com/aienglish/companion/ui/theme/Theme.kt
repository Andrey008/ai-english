package com.aienglish.companion.ui.theme

import android.app.Activity
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.unit.dp
import androidx.core.view.WindowCompat
import com.aienglish.companion.data.Appearance
import com.aienglish.companion.data.ThemeMode

// The app's own palette: indigo primary, teal secondary, on soft neutral
// surfaces. Used unless "wallpaper colors" is on in Settings.
private val LightColors = lightColorScheme(
    primary = Color(0xFF4C51C6),
    onPrimary = Color.White,
    primaryContainer = Color(0xFFE1E0FF),
    onPrimaryContainer = Color(0xFF0B0A6B),
    secondary = Color(0xFF00897B),
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFC9F0E8),
    onSecondaryContainer = Color(0xFF00201C),
    tertiary = Color(0xFFB4508C),
    tertiaryContainer = Color(0xFFFFD8EA),
    onTertiaryContainer = Color(0xFF3B0029),
    background = Color(0xFFF8F8FC),
    onBackground = Color(0xFF1B1B21),
    surface = Color(0xFFF8F8FC),
    onSurface = Color(0xFF1B1B21),
    surfaceVariant = Color(0xFFE4E1EC),
    onSurfaceVariant = Color(0xFF47464F),
    surfaceContainerLowest = Color.White,
    surfaceContainerLow = Color(0xFFF2F2F8),
    surfaceContainer = Color(0xFFECECF3),
    surfaceContainerHigh = Color(0xFFE6E6EE),
    surfaceContainerHighest = Color(0xFFE0E0E9),
    outline = Color(0xFF787680),
    outlineVariant = Color(0xFFC8C5D0),
    error = Color(0xFFBA1A1A),
    errorContainer = Color(0xFFFFDAD6),
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFFC0C1FF),
    onPrimary = Color(0xFF1A1A8C),
    primaryContainer = Color(0xFF3438AD),
    onPrimaryContainer = Color(0xFFE1E0FF),
    secondary = Color(0xFF6FD8C6),
    onSecondary = Color(0xFF003731),
    secondaryContainer = Color(0xFF005047),
    onSecondaryContainer = Color(0xFFC9F0E8),
    tertiary = Color(0xFFFFAFD6),
    tertiaryContainer = Color(0xFF7F2E62),
    onTertiaryContainer = Color(0xFFFFD8EA),
    background = Color(0xFF121318),
    onBackground = Color(0xFFE4E1E9),
    surface = Color(0xFF121318),
    onSurface = Color(0xFFE4E1E9),
    surfaceVariant = Color(0xFF47464F),
    onSurfaceVariant = Color(0xFFC8C5D0),
    surfaceContainerLowest = Color(0xFF0D0E13),
    surfaceContainerLow = Color(0xFF1B1B21),
    surfaceContainer = Color(0xFF1F1F25),
    surfaceContainerHigh = Color(0xFF292A30),
    surfaceContainerHighest = Color(0xFF34343B),
    outline = Color(0xFF928F9A),
    outlineVariant = Color(0xFF47464F),
    error = Color(0xFFFFB4AB),
    errorContainer = Color(0xFF93000A),
)

private val AppShapes = Shapes(
    small = RoundedCornerShape(10.dp),
    medium = RoundedCornerShape(16.dp),
    large = RoundedCornerShape(24.dp),
)

@Composable
fun AiEnglishTheme(appearance: Appearance = Appearance(), content: @Composable () -> Unit) {
    val darkTheme = when (appearance.themeMode) {
        ThemeMode.SYSTEM -> isSystemInDarkTheme()
        ThemeMode.LIGHT -> false
        ThemeMode.DARK -> true
    }
    // minSdk 34 already guarantees API 31+ (dynamic color availability).
    val context = LocalContext.current
    val colorScheme = when {
        appearance.wallpaperColors && darkTheme -> dynamicDarkColorScheme(context)
        appearance.wallpaperColors -> dynamicLightColorScheme(context)
        darkTheme -> DarkColors
        else -> LightColors
    }

    // Edge-to-edge: the system bars are transparent, so their icons must
    // follow the app's theme, not the system's.
    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as Activity).window
            WindowCompat.getInsetsController(window, view).apply {
                isAppearanceLightStatusBars = !darkTheme
                isAppearanceLightNavigationBars = !darkTheme
            }
        }
    }

    MaterialTheme(colorScheme = colorScheme, shapes = AppShapes, content = content)
}
