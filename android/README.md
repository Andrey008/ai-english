# AI English — Android client

Kotlin + Jetpack Compose client for the AI English Voice Companion server
(`/server`). See `Docs/stories/epic-05/` (repo root, gitignored) for the
full story breakdown and `Docs/decisions/ADR-0009-android-client-technical-foundations.md`
for the technical choices behind this module (raw `AudioTrack`/`AudioRecord`,
OkHttp, no DI framework, sideload-only).

## Prerequisites

- Android SDK, API 34 platform + build-tools 34.0.0, `adb`. On this dev
  machine these were installed via `brew install --cask
  android-commandlinetools` — see
  `Docs/decisions/ADR-0011-android-toolchain-install.md` for exact
  versions and (important) how to remove them later.
- No global Gradle install needed — use the wrapper (`./gradlew`), which
  self-downloads the pinned Gradle 8.9 distribution into
  `~/.gradle/wrapper/dists` on first run (not part of this repo).
- `local.properties` (gitignored, machine-specific) must contain
  `sdk.dir=<path to your Android SDK>`, e.g.:
  ```
  sdk.dir=/opt/homebrew/share/android-commandlinetools
  ```
  Alternatively, export `$ANDROID_HOME` before invoking Gradle.

## Build & install

```sh
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Sideload only (`ADR-0009`) — no Play Store distribution, ever, per
`Docs/PRD.md`'s non-goals.

## Running against a real server

On first launch the app asks for the Mac server's host/port (Tailscale
hostname or IP; default port `8000`, matching `/server`'s default
`uvicorn` port). No auto-discovery — this is always entered manually.
