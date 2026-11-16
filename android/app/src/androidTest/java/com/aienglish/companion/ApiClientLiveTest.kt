package com.aienglish.companion

import androidx.test.platform.app.InstrumentationRegistry
import com.aienglish.companion.data.ServerConfig
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.aienglish.companion.data.api.ApiClient
import com.aienglish.companion.data.api.ApiResult
import com.aienglish.companion.data.api.CharacterPreset
import com.aienglish.companion.data.api.CorrectionStyle
import com.aienglish.companion.data.api.Gender
import com.aienglish.companion.data.api.ScenarioDefinition
import com.aienglish.companion.data.api.TtsEngine
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Live verification for STORY-05-02 — requires a real `/server` reachable
 * from the emulator/device, not mocked (mirrors `server/scripts/`'s
 * throwaway-but-kept live check convention). `10.0.2.2` is the Android
 * emulator's alias for the host machine's loopback (QEMU slirp networking),
 * so this expects the server running on the dev Mac at `127.0.0.1:8000`
 * (`uv run uvicorn app.main:app --host 127.0.0.1 --port 8000`). Not runnable
 * on a real device or in CI without a reachable server — a dev-machine
 * check, not a hermetic unit test.
 */
@RunWith(AndroidJUnit4::class)
class ApiClientLiveTest {

    private val client = ApiClient(configProvider = {
        // Instrumentation arg: -Pandroid.testInstrumentationRunnerArguments.aiEnglishToken=<token>
        ServerConfig(
            host = "10.0.2.2", port = 8000,
            token = InstrumentationRegistry.getArguments().getString("aiEnglishToken").orEmpty(),
        )
    })

    @Test
    fun listCharacters_includesSeededDefault() = runBlocking {
        val result = client.listCharacters()
        assertTrue("expected Success, got $result", result is ApiResult.Success)
        val characters = (result as ApiResult.Success).data
        assertTrue(characters.any { it.id == "alex_default" })
    }

    @Test
    fun getCharacter_unknownId_returns404() = runBlocking {
        val result = client.getCharacter("does_not_exist_${System.currentTimeMillis()}")
        assertTrue(
            "expected HttpError(404), got $result",
            result is ApiResult.HttpError && result.code == 404,
        )
    }

    @Test
    fun characterCrud_fullRoundTrip() = runBlocking {
        val id = "story0502_test_${System.currentTimeMillis()}"
        val preset = CharacterPreset(
            id = id,
            name = "Story Test",
            gender = Gender.MALE,
            roleDescription = "A character created by STORY-05-02's live verification test.",
            ttsVoiceId = "en_US-lessac-medium",
            ttsEngine = TtsEngine.PIPER,
            correctionStyle = CorrectionStyle.OFF,
        )
        try {
            val created = client.createCharacter(preset)
            assertTrue("expected Success, got $created", created is ApiResult.Success)
            assertEquals(preset, (created as ApiResult.Success).data)

            val duplicate = client.createCharacter(preset)
            assertTrue(
                "expected HttpError(409), got $duplicate",
                duplicate is ApiResult.HttpError && duplicate.code == 409,
            )

            val updated = preset.copy(roleDescription = "Updated by the live test.")
            val updateResult = client.updateCharacter(id, updated)
            assertTrue("expected Success, got $updateResult", updateResult is ApiResult.Success)

            val fetched = client.getCharacter(id)
            assertTrue("expected Success, got $fetched", fetched is ApiResult.Success)
            assertEquals(updated, (fetched as ApiResult.Success).data)
        } finally {
            client.deleteCharacter(id)
        }

        val afterDelete = client.getCharacter(id)
        assertTrue(
            "expected HttpError(404) after delete, got $afterDelete",
            afterDelete is ApiResult.HttpError && afterDelete.code == 404,
        )
    }

    @Test
    fun scenarioCrud_fullRoundTrip() = runBlocking {
        val id = "story0502_scenario_${System.currentTimeMillis()}"
        val scenario = ScenarioDefinition(
            id = id,
            title = "Story 05-02 test scenario",
            difficulty = 1,
            characterRolePromptAddendum = "Test addendum.",
            goal = "Verify the scenario REST client.",
            openingLineHint = "Hi, this is a test scenario.",
        )
        try {
            val created = client.createScenario(scenario)
            assertTrue("expected Success, got $created", created is ApiResult.Success)

            val duplicate = client.createScenario(scenario)
            assertTrue(
                "expected HttpError(409), got $duplicate",
                duplicate is ApiResult.HttpError && duplicate.code == 409,
            )

            val list = client.listScenarios()
            assertTrue("expected Success, got $list", list is ApiResult.Success)
            assertTrue((list as ApiResult.Success).data.any { it.id == id })
        } finally {
            client.deleteScenario(id)
        }

        val afterDelete = client.getScenario(id)
        assertTrue(
            "expected HttpError(404) after delete, got $afterDelete",
            afterDelete is ApiResult.HttpError && afterDelete.code == 404,
        )
    }
}
