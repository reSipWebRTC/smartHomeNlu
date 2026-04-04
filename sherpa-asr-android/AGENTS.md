# Repository Guidelines

## Project Structure & Module Organization
This repository is a single Android app module, `:app`. Kotlin sources live under `app/src/main/java/com/example/asrapp/` and are grouped by responsibility: `audio/`, `model/`, `network/`, `router/`, `ui/`, `utils/`, and `viewmodel/`. Compose UI code is in `ui/`, while app startup stays in `AsrApplication.kt` and `MainActivity.kt`. Runtime models are expected in `app/src/main/assets/asr/` and `app/src/main/assets/vad/`. Native libraries and vendor binaries live in `app/src/main/jniLibs/` and `app/libs/`. Ignore generated output under `app/build/`, `build/`, and local files such as `local.properties` and `java_pid*.hprof`.

## Build, Test, and Development Commands
Use the Gradle wrapper from the repo root:

- `./gradlew assembleDebug`: build the debug APK.
- `./gradlew installDebug`: install the debug build on a connected device or emulator.
- `./gradlew lint`: run Android lint checks.
- `./gradlew testDebugUnitTest`: run local JVM unit tests once they are added.
- `./gradlew connectedDebugAndroidTest`: run device or emulator instrumentation tests.

The project targets Android SDK 34, min SDK 26, Java/Kotlin 17, and ships `arm64-v8a` plus `armeabi-v7a` ABIs.

## Coding Style & Naming Conventions
Follow the existing Kotlin style in `app/src/main/java`: 4-space indentation, one top-level class or file concern, and descriptive `PascalCase` for classes, `camelCase` for functions and properties, and `UPPER_SNAKE_CASE` for constants. Keep Compose screens and reusable components split by feature, for example `AsrScreen.kt` and `ui/components/CommandCard.kt`. Prefer small state holders in `viewmodel/` and keep platform or network wiring out of composables.

## Testing Guidelines
There are currently no checked-in test source sets. Add JVM tests under `app/src/test/` and instrumentation or Compose UI tests under `app/src/androidTest/`. Name test files after the target, such as `FillerWordFilterTest.kt` or `AsrScreenTest.kt`. Cover filler-word filtering, routing, and network fallback logic before changing recognition behavior.

## Commit & Pull Request Guidelines
Git history is not available in this workspace snapshot, so no repository-specific commit convention could be verified. Use short, imperative commit subjects such as `Add offline model validation` and keep each commit focused. For pull requests, include a summary, affected flows, setup changes for models or assets, linked issues, and screenshots or recordings for UI changes.

## Configuration Tips
Large ONNX model files are not fully tracked here. If asset filenames change, update the paths in `AsrModelLoader.kt` to match the downloaded model package.
