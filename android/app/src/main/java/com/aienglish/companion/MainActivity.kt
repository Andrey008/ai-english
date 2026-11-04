package com.aienglish.companion

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import com.aienglish.companion.ui.AiEnglishApp

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val appContainer = (application as AiEnglishApplication).appContainer
        setContent {
            AiEnglishApp(appContainer)
        }
    }
}
