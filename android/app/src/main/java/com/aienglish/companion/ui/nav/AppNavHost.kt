package com.aienglish.companion.ui.nav

import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Mic
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
import com.aienglish.companion.ui.screens.CharacterListScreen
import com.aienglish.companion.ui.screens.ServerSetupScreen
import com.aienglish.companion.ui.screens.SettingsScreen
import com.aienglish.companion.ui.screens.VoiceSessionScreen

private data class BottomDestination(
    val route: String,
    val label: String,
    val icon: androidx.compose.ui.graphics.vector.ImageVector,
)

private val bottomDestinations = listOf(
    BottomDestination(Routes.CharacterList, "Characters", Icons.AutoMirrored.Filled.List),
    BottomDestination(Routes.CharacterCreator, "Create", Icons.Default.Add),
    BottomDestination(Routes.VoiceSession, "Session", Icons.Default.Mic),
    BottomDestination(Routes.Settings, "Settings", Icons.Default.Settings),
)

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

    Scaffold(
        bottomBar = {
            if (currentRoute != Routes.ServerSetup) {
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
            modifier = Modifier.padding(padding),
        ) {
            composable(Routes.ServerSetup) {
                ServerSetupScreen(
                    store = serverConfigStore,
                    onSaved = {
                        navController.navigate(Routes.CharacterList) {
                            popUpTo(Routes.ServerSetup) { inclusive = true }
                        }
                    },
                )
            }
            composable(Routes.CharacterList) {
                CharacterListScreen(
                    onCreateNew = { navigateToTab(Routes.CharacterCreator) },
                    onEdit = { characterId ->
                        navController.navigate(Routes.characterEditor(characterId))
                    },
                )
            }
            composable(Routes.CharacterCreator) {
                CharacterCreatorScreen(
                    characterId = null,
                    onDone = { navigateToTab(Routes.CharacterList) },
                )
            }
            composable(
                route = Routes.CharacterEditor,
                arguments = listOf(navArgument("characterId") { type = NavType.StringType }),
            ) { backStackEntry ->
                CharacterCreatorScreen(
                    characterId = backStackEntry.arguments?.getString("characterId"),
                    onDone = { navController.popBackStack() },
                )
            }
            composable(Routes.VoiceSession) { VoiceSessionScreen() }
            composable(Routes.Settings) { SettingsScreen() }
        }
    }
}
