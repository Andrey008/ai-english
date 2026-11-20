package com.aienglish.companion.ui.screens

import android.Manifest
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.aienglish.companion.ui.LocalAppContainer

class MicPermissionState(val granted: Boolean, val request: () -> Unit)

/** RECORD_AUDIO, requested together with POST_NOTIFICATIONS — but only
 * the mic gates starting a session: a denied notification permission
 * just means the foreground-service notification (STORY-05-08) won't be
 * visible while backgrounded; the session still works. */
@Composable
fun rememberMicPermission(): MicPermissionState {
    val appContainer = LocalAppContainer.current
    var granted by remember { mutableStateOf(appContainer.audioCapture.hasPermission) }
    val launcher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) { result -> granted = result[Manifest.permission.RECORD_AUDIO] == true }

    // A permission granted externally (Settings, or adb) never fires the
    // launcher callback above — `pm grant` from outside the app left the
    // screen stuck showing the blocked state. Re-check on every resume, so
    // "grant it in Settings, come back" works without an app restart.
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) granted = appContainer.audioCapture.hasPermission
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }
    return MicPermissionState(granted) {
        launcher.launch(arrayOf(Manifest.permission.RECORD_AUDIO, Manifest.permission.POST_NOTIFICATIONS))
    }
}
