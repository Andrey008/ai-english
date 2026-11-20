package com.aienglish.companion.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** ADR-0017: the token never goes over plain HTTP to a public host. */
class ServerConfigTest {

    @Test
    fun privateHosts() {
        listOf(
            "127.0.0.1", "localhost", "10.0.2.2", "192.168.1.20", "172.16.0.5", "172.31.255.1",
            "100.101.102.103", "macbook", "macbook.tail1234.ts.net", "mac.local",
        ).forEach { assertTrue(it, isPrivateHost(it)) }
    }

    @Test
    fun publicHosts() {
        listOf(
            "8.8.8.8", "172.32.0.1", "100.128.0.1", "192.169.0.1", "english.example.com", "1.2.3", "",
        ).forEach { assertFalse(it, isPrivateHost(it)) }
    }

    @Test
    fun publicHostNeedsTls() {
        val plain = ServerConfig(host = "english.example.com", port = 443, token = "aie_x")
        assertTrue(plain.cleartextBlocked)
        assertTrue(plain.connectProblem!!.contains("HTTPS"))
        val tls = plain.copy(useTls = true)
        assertNull(tls.connectProblem)
        assertEquals("https://english.example.com:443", tls.baseUrl)
    }

    @Test
    fun tokenIsRequired() {
        val config = ServerConfig(host = "192.168.1.20")
        assertFalse(config.isConfigured)
        assertTrue(config.connectProblem!!.contains("token"))
        assertEquals("Bearer aie_x", config.copy(token = "aie_x").authorizationHeader)
    }
}
