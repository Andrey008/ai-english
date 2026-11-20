package com.aienglish.companion.ui.nav

import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.BarChart
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.aienglish.companion.data.ServerConfigStore
import com.aienglish.companion.ui.screens.CharacterCreatorScreen
import com.aienglish.companion.ui.screens.CharacterGuideScreen
import com.aienglish.companion.ui.screens.CharacterListScreen
import com.aienglish.companion.ui.screens.ConversationDetailScreen
import com.aienglish.companion.ui.screens.ConversationListScreen
import com.aienglish.companion.ui.screens.NewConversationScreen
import com.aienglish.companion.ui.screens.ServerSetupScreen
import com.aienglish.companion.ui.screens.SettingsScreen
import com.aienglish.companion.ui.screens.StatsScreen
import com.aienglish.companion.ui.screens.VoiceSessionScreen

private data class BottomDestination(
    val route: String,
    val label: String,
    val icon: androidx.compose.ui.graphics.vector.ImageVector,
)

private val bottomDestinations = listOf(
    BottomDestination(Routes.Conversations, "Conversations", Icons.AutoMirrored.Filled.Chat),
    BottomDestination(Routes.CharacterList, "Characters", Icons.AutoMirrored.Filled.List),
    BottomDestination(Routes.Stats, "Stats", Icons.Default.BarChart),
    BottomDestination(Routes.Settings, "Settings", Icons.Default.Settings),
)
private val tabRoutes = bottomDestinations.map { it.route }.toSet()

@Composable
fun AppNavHost(serverConfigStore: ServerConfigStore, startDestination: String) {
    val navController = rememberNavController()
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route

    // Bottom-nav tab switching only — every tab route here is arg-free by
    // construction (see Routes.kt's note on CharacterCreator vs
    // CharacterEditor). Don't reuse this for anything that carries an
    // argument: saveState/restoreState identifies a destination by its
    // route pattern alone, so two navigations to the same pattern with
    // different argument values collide.
    fun navigateToTab(route: String) {
        navController.navigate(route) {
            popUpTo(navController.graph.findStartDestination().id) {
                saveState = true
            }
            launchSingleTop = true
            restoreState = true
        }
    }

    // Edge-to-edge: each screen's own Scaffold handles the system bars; this
    // outer one only adds the bottom bar's height, consumed so the inner
    // ones don't pad for the navigation bar a second time.
    Scaffold(
        contentWindowInsets = WindowInsets(0, 0, 0, 0),
        bottomBar = {
            if (currentRoute in tabRoutes) {
                NavigationBar {
                    bottomDestinations.forEach { dest ->
                        NavigationBarItem(
                            selected = backStackEntry?.destination?.hierarchy
                                ?.any { it.route == dest.route } == true,
                            onClick = { navigateToTab(dest.route) },
                            icon = { Icon(dest.icon, contentDescription = dest.label) },
                            label = { Text(dest.label) },
                        )
                    }
                }
            }
        },
    ) { padding ->
        NavHost(
            navController = navController,
            startDestination = startDestination,
            modifier = Modifier.padding(padding).consumeWindowInsets(padding),
        ) {
            composable(Routes.ServerSetup) {
                ServerSetupScreen(
                    store = serverConfigStore,
                    onSaved = {
                        navController.navigate(Routes.Conversations) {
                            popUpTo(Routes.ServerSetup) { inclusive = true }
                        }
                    },
                )
            }
            // A started conversation replaces the screen it was started
            // from, so back from it lands on the list.
            fun openSession() {
                navController.navigate(Routes.VoiceSession) {
                    popUpTo(Routes.Conversations)
                    launchSingleTop = true
                }
            }
            composable(Routes.Conversations) {
                ConversationListScreen(
                    onNew = { navController.navigate(Routes.NewConversation) },
                    onOpen = { id -> navController.navigate(Routes.conversationDetail(id)) },
                    onOpenActive = { openSession() },
                )
            }
            composable(Routes.NewConversation) {
                NewConversationScreen(
                    onBack = { navController.popBackStack() },
                    onStarted = { openSession() },
                )
            }
            composable(
                route = Routes.ConversationDetail,
                arguments = listOf(navArgument("conversationId") { type = NavType.StringType }),
            ) { backStackEntry ->
                ConversationDetailScreen(
                    conversationId = backStackEntry.arguments?.getString("conversationId").orEmpty(),
                    onBack = { navController.popBackStack() },
                    onContinued = { openSession() },
                )
            }
            composable(Routes.VoiceSession) {
                VoiceSessionScreen(onClose = { navController.popBackStack() })
            }
            composable(Routes.CharacterList) {
                CharacterListScreen(
                    onCreateNew = { navController.navigate(Routes.CharacterCreator) },
                    onOpenGuide = { navController.navigate(Routes.CharacterGuide) },
                    onEdit = { characterId ->
                        navController.navigate(Routes.characterEditor(characterId))
                    },
                )
            }
            composable(Routes.CharacterCreator) {
                CharacterCreatorScreen(
                    characterId = null,
                    onDone = { navController.popBackStack() },
                    onOpenGuide = { navController.navigate(Routes.CharacterGuide) },
                )
            }
            composable(Routes.CharacterGuide) {
                CharacterGuideScreen(
                    onBack = { navController.popBackStack() },
                    // Opened from the creator: go back to it; from the list: replace the guide with it.
                    onCreate = {
                        if (navController.previousBackStackEntry?.destination?.route == Routes.CharacterCreator) {
                            navController.popBackStack()
                        } else {
                            navController.navigate(Routes.CharacterCreator) {
                                popUpTo(Routes.CharacterGuide) { inclusive = true }
                            }
                        }
                    },
                )
            }
            composable(
                route = Routes.CharacterEditor,
                arguments = listOf(navArgument("characterId") { type = NavType.StringType }),
            ) { backStackEntry ->
                CharacterCreatorScreen(
                    characterId = backStackEntry.arguments?.getString("characterId"),
                    onDone = { navController.popBackStack() },
                    onOpenGuide = { navController.navigate(Routes.CharacterGuide) },
                )
            }
            composable(Routes.Stats) { StatsScreen() }
            composable(Routes.Settings) { SettingsScreen() }
        }
    }
}
