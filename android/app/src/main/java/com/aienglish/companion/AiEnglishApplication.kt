package com.aienglish.companion

import android.app.Application

/** Owns the single [AppContainer] instance for the app's whole process
 * lifetime. Needed from `STORY-05-08` on: a `Service` and an `Activity`
 * are separate Android components Android can instantiate independently
 * — a `Service` has no way to reach a container built as a local
 * variable inside `MainActivity.onCreate`. Application scope is the
 * standard place both can reach the same instance from. */
class AiEnglishApplication : Application() {
    val appContainer: AppContainer by lazy { AppContainer(this) }
}
