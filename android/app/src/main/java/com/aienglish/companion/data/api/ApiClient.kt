package com.aienglish.companion.data.api

import com.aienglish.companion.data.ServerConfig
import com.aienglish.companion.data.ServerConfigStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.withContext
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

private val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()

/** Typed client for `/characters`, `/scenarios`, `/conversations` and `/stats`
 * (`server/app/main.py`).
 * Reads the server config fresh on every call (via [configProvider]) so a
 * user changing it in Settings (`STORY-05-10`) doesn't require restarting
 * the app. Every request carries the device token (ADR-0017). */
class ApiClient(
    private val configProvider: suspend () -> ServerConfig,
    private val httpClient: OkHttpClient = OkHttpClient(),
) {
    constructor(
        serverConfigStore: ServerConfigStore,
        httpClient: OkHttpClient = OkHttpClient(),
    ) : this(
        configProvider = { serverConfigStore.configFlow.first() },
        httpClient = httpClient,
    )

    private val json = Json { ignoreUnknownKeys = true }

    suspend fun listCharacters(): ApiResult<List<CharacterPreset>> =
        decoded(request("GET", "/characters"))

    suspend fun getCharacter(id: String): ApiResult<CharacterPreset> =
        decoded(request("GET", "/characters/$id"))

    suspend fun createCharacter(preset: CharacterPreset): ApiResult<CharacterPreset> =
        decoded(request("POST", "/characters", json.encodeToString(preset)))

    suspend fun updateCharacter(id: String, preset: CharacterPreset): ApiResult<CharacterPreset> =
        decoded(request("PUT", "/characters/$id", json.encodeToString(preset)))

    suspend fun deleteCharacter(id: String): ApiResult<Unit> =
        toUnit(raw(request("DELETE", "/characters/$id")))

    suspend fun deleteCharacterMemory(id: String): ApiResult<Unit> =
        toUnit(raw(request("DELETE", "/characters/$id/memory")))

    suspend fun listScenarios(): ApiResult<List<ScenarioDefinition>> =
        decoded(request("GET", "/scenarios"))

    suspend fun getScenario(id: String): ApiResult<ScenarioDefinition> =
        decoded(request("GET", "/scenarios/$id"))

    suspend fun createScenario(scenario: ScenarioDefinition): ApiResult<ScenarioDefinition> =
        decoded(request("POST", "/scenarios", json.encodeToString(scenario)))

    suspend fun updateScenario(id: String, scenario: ScenarioDefinition): ApiResult<ScenarioDefinition> =
        decoded(request("PUT", "/scenarios/$id", json.encodeToString(scenario)))

    suspend fun deleteScenario(id: String): ApiResult<Unit> =
        toUnit(raw(request("DELETE", "/scenarios/$id")))

    suspend fun listConversations(): ApiResult<List<ConversationSummary>> =
        decoded(request("GET", "/conversations"))

    suspend fun getConversation(id: String): ApiResult<ConversationDetail> =
        decoded(request("GET", "/conversations/$id"))

    suspend fun renameConversation(id: String, title: String): ApiResult<ConversationDetail> =
        decoded(request("PATCH", "/conversations/$id", json.encodeToString(ConversationRename(title))))

    suspend fun deleteConversation(id: String): ApiResult<Unit> =
        toUnit(raw(request("DELETE", "/conversations/$id")))

    /** Ask the server to load the model now (it answers at once, the load
     * runs in the background) so a conversation started soon after
     * doesn't wait ~10s for it. Fire and forget. */
    suspend fun warmup(): ApiResult<Unit> = toUnit(raw(request("POST", "/warmup", "")))

    /** Practice stats over the last [days] days, with day boundaries in [tz]
     * (an IANA zone id, the phone's own by default). */
    suspend fun stats(days: Int = 30, tz: String = java.time.ZoneId.systemDefault().id): ApiResult<PracticeStats> =
        decoded(request("GET", "/stats?days=$days&tz=${java.net.URLEncoder.encode(tz, "UTF-8")}"))

    /** The device this token belongs to — checks address and token together. */
    suspend fun authMe(): ApiResult<AuthMe> = decoded(request("GET", "/auth/me"))

    private suspend fun request(method: String, path: String, jsonBody: String? = null): Request? {
        val config = configProvider()
        if (config.connectProblem != null) return null
        val builder = Request.Builder()
            .url("${config.baseUrl}$path")
            .header("Authorization", config.authorizationHeader)
        when (method) {
            "GET" -> builder.get()
            "DELETE" -> builder.delete()
            "POST" -> builder.post((jsonBody ?: "").toRequestBody(JSON_MEDIA_TYPE))
            "PUT" -> builder.put((jsonBody ?: "").toRequestBody(JSON_MEDIA_TYPE))
            "PATCH" -> builder.patch((jsonBody ?: "").toRequestBody(JSON_MEDIA_TYPE))
        }
        return builder.build()
    }

    private suspend fun raw(request: Request?): ApiResult<String> = withContext(Dispatchers.IO) {
        if (request == null) {
            val problem = configProvider().connectProblem ?: "Server is not configured."
            return@withContext ApiResult.NetworkError(IllegalStateException(problem))
        }
        try {
            httpClient.newCall(request).execute().use { response ->
                val body = response.body?.string()
                if (response.isSuccessful) {
                    ApiResult.Success(body ?: "")
                } else {
                    ApiResult.HttpError(response.code, body)
                }
            }
        } catch (e: Exception) {
            ApiResult.NetworkError(e)
        }
    }

    private suspend inline fun <reified T> decoded(request: Request?): ApiResult<T> =
        when (val result = raw(request)) {
            is ApiResult.Success -> try {
                ApiResult.Success(json.decodeFromString<T>(result.data))
            } catch (e: Exception) {
                ApiResult.NetworkError(e)
            }
            is ApiResult.HttpError -> result
            is ApiResult.NetworkError -> result
        }

    private fun toUnit(result: ApiResult<String>): ApiResult<Unit> = when (result) {
        is ApiResult.Success -> ApiResult.Success(Unit)
        is ApiResult.HttpError -> result
        is ApiResult.NetworkError -> result
    }
}
