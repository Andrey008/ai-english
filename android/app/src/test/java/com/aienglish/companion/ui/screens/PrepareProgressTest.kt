package com.aienglish.companion.ui.screens

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PrepareProgressTest {
    @Test
    fun fillsToNinetyAtTheEstimateThenCreepsBelowHundred() {
        assertEquals(0f, prepareProgress(0.0, 10.0), 0.001f)
        assertEquals(0.45f, prepareProgress(5.0, 10.0), 0.001f)
        assertEquals(0.9f, prepareProgress(10.0, 10.0), 0.001f)
        val late = prepareProgress(60.0, 10.0)
        assertTrue(late > 0.98f && late < 1f)
    }

    @Test
    fun neverGoesBackwards() {
        var last = 0f
        for (t in 0..300) {
            val p = prepareProgress(t / 10.0, 7.0)
            assertTrue(p >= last)
            last = p
        }
    }
}
