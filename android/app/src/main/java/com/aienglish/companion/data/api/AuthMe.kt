package com.aienglish.companion.data.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** `GET /auth/me` (ADR-0017): which device token the server accepted. */
@Serializable
data class AuthMe(
    val device: AuthDevice? = null,
    @SerialName("auth_required") val authRequired: Boolean = true,
)

@Serializable
data class AuthDevice(val id: String, val name: String)
