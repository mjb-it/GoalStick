# GoalStick Android App

Android companion app for the GoalStick NHL goal celebration light system.

## Features

- Finds the GoalStick over Bluetooth (classic RFCOMM / SPP)
- Remembers the last GoalStick and reconnects without a scan
- Sends WiFi credentials during pairing mode
- Sets the team and broadcast delay at any time
- Fires a test celebration
- Shows the Pi's IP address once it is online

## How It Talks to the Pi

Messages are JSON objects, one per line, in both directions. Requests are
serialized so a config fetch and a button tap never interleave. Each request
waits up to 15 seconds for a reply; on timeout the socket is closed and the
UI shows an error.

- **Pairing mode** (hold the GoalStick button 3 seconds, light blinks blue):
  the Pi is discoverable and accepts WiFi credentials. Scan, pick the device,
  enter the network name and password, tap Send Configuration.
- **Normal operation**: the Pi is connectable but WiFi changes are refused.
  Use Reconnect to Last GoalStick to change the team or delay, or to test the
  lights. Leave the password field empty so no WiFi change is attempted.

The app connects with an insecure RFCOMM socket by SPP UUID and falls back to
channel 1 if the Pi's SDP record is missing. Only named devices are listed,
with GoalStick-looking names first.

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
