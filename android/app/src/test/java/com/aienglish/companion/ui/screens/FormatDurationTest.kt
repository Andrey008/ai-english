package com.aienglish.companion.ui.screens

import org.junit.Assert.assertEquals
import org.junit.Test

class FormatDurationTest {
    @Test
    fun formatsHoursMinutesAndSeconds() {
        assertEquals("0m", formatDuration(0))
        assertEquals("45s", formatDuration(45))
        assertEquals("12m", formatDuration(12 * 60 + 30))
        assertEquals("1h 05m", formatDuration(3600 + 5 * 60))
    }
}
