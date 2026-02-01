# GoalStick Android App

Android companion app for the GoalStick NHL goal celebration light system.

## Features

- Monitor NHL games in real-time
- Configure team settings
- Control ESP32 LED light strips
- View game statistics

## Requirements

- Android Studio Hedgehog (2023.1.1) or newer
- Android SDK 34
- Kotlin 1.9+

## Project Structure

```
Android/
├── app/
│   ├── src/main/
│   │   ├── java/com/goalstick/android/  # Kotlin source
│   │   ├── res/                          # Resources
│   │   └── AndroidManifest.xml
│   └── build.gradle
├── build.gradle
├── settings.gradle
└── README.md
```

## Building

1. Open the `Android` directory in Android Studio
2. Sync Gradle files
3. Build → Make Project (Ctrl+F9)

## Running

1. Connect an Android device or start an emulator
2. Run → Run 'app' (Shift+F10)

## Architecture

- **Language**: Kotlin
- **UI**: XML layouts with Material3 components
- **Min SDK**: 24 (Android 7.0)
- **Target SDK**: 34 (Android 14)
