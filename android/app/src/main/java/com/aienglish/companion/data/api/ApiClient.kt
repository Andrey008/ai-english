package com.aienglish.companion.data.api

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

/** Typed client for `/characters` and `/scenarios` (`server/app/main.py`).
 * Reads the server address fresh on every call (via [baseUrlProvider]) so a
 * user changing it in Settings (`STORY-05-10`) doesn't require restarting
 * the app. */
class ApiClient(
    private val baseUrlProvider: suspend () -> String,
    private val httpClient: OkHttpClient = OkHttpClient(),
) {
    constructor(
        serverConfigStore: ServerConfigStore,
        httpClient: OkHttpClient = OkHttpClient(),
    ) : this(
        baseUrlProvider = {
            val config = serverConfigStore.configFlow.first()
            "http://${config.host}:${config.port}"
        },
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

    private suspend fun request(method: String, path: String, jsonBody: String? = null): Request {
        val url = "${baseUrlProvider()}$path"
        val builder = Request.Builder().url(url)
        when (method) {
            "GET" -> builder.get()
            "DELETE" -> builder.delete()
            "POST" -> builder.post((jsonBody ?: "").toRequestBody(JSON_MEDIA_TYPE))
            "PUT" -> builder.put((jsonBody ?: "").toRequestBody(JSON_MEDIA_TYPE))
        }
        return builder.build()
    }

    private suspend fun raw(request: Request): ApiResult<String> = withContext(Dispatchers.IO) {
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

    private suspend inline fun <reified T> decoded(request: Request): ApiResult<T> =
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
