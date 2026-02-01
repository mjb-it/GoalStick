# GoalStick

An NHL goal celebration system that triggers LED light shows when your favorite team scores. The system consists of three components:

- **Raspberry Pi Service** (Python) - Monitors NHL games and detects goals
- **Android App** (Kotlin) - Companion app for configuration via Bluetooth
- **ESP32 Firmware** (Arduino/C++) - Controls WS2812B LED strip animations

## Repository Structure

```
GoalStick/
├── PythonSrc/       # Raspberry Pi Python service
├── Android/         # Android companion app
├── ESP32/           # ESP32 LED controller firmware
├── Makefile         # Build and test automation
└── README.md
```

---

# Raspberry Pi Service (Python)

The core service that monitors NHL games and communicates with the ESP32 to trigger celebrations.

## Requirements

- Raspberry Pi Zero 2 W (or any Pi with GPIO)
- Python 3.9+
- Serial connection to ESP32

## Installation

```bash
cd PythonSrc
pip install -e .
```

Or using Make:
```bash
make python-install
```

## Usage

```bash
cd PythonSrc

# Start the goal monitoring service
python main.py

# Set your team (persists across reboots)
python main.py --team WSH

# Show currently configured team
python main.py --show-team

# Enter Bluetooth pairing mode
python main.py --pair
```

## Testing

```bash
# Run unit tests (69 tests)
make python-test

# Run with coverage report
make python-test-cov
```

## Configuration Options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `team_abbr` | str | "WSH" | NHL team abbreviation |
| `check_interval` | float | 2.0 | Seconds between goal checks during live games |
| `daily_check_hour` | int | 8 | Hour (24-hour format) to check daily schedule |
| `pre_game_wake_minutes` | int | 5 | Minutes before game to wake up |
| `serial_port` | str | "/dev/serial0" | Serial port for ESP32 communication |
| `serial_baud_rate` | int | 115200 | Baud rate for serial communication |
| `pairing_button_pin` | int | 17 | BCM GPIO pin for pairing button |
| `esp32_reset_pin` | int | 27 | BCM GPIO pin connected to ESP32 EN |

## Dependencies

- `nhlpy` - NHL API client
- `python-dateutil` - Date parsing utilities
- `pyserial` - Serial communication with ESP32
- `RPi.GPIO` - GPIO control (optional, for button/reset)

---

# Android App (Kotlin)

Companion app for configuring the GoalStick via Bluetooth.

## Requirements

- Android Studio Hedgehog (2023.1.1) or newer
- Android SDK 34
- Java 17 (for command-line builds)

## Features

- Bluetooth device discovery and pairing
- WiFi credential configuration
- NHL team selection (all 32 teams)
- Send configuration to Raspberry Pi

## Building

### Using Android Studio (Recommended)

1. Open `Android/` folder in Android Studio
2. Sync Gradle files
3. Build → Build Bundle(s) / APK(s) → Build APK(s)

### Using Command Line

```bash
# Requires Android SDK and Java 17
make android-build

# APK location:
# Android/app/build/outputs/apk/debug/app-debug.apk
```

### Installing on Device

```bash
# With device connected via USB
make android-install

# Or manually:
adb install Android/app/build/outputs/apk/debug/app-debug.apk
```

## Project Structure

```
Android/
├── app/src/main/
│   ├── java/com/goalstick/android/
│   │   ├── MainActivity.kt           # Main UI
│   │   ├── bluetooth/BluetoothManager.kt  # BT connection
│   │   ├── data/ConfigurationData.kt # Team data
│   │   └── ui/                        # UI components
│   ├── res/layout/                    # XML layouts
│   └── AndroidManifest.xml
├── build.gradle
└── settings.gradle
```

---

# ESP32 Firmware (Arduino)

Controls the WS2812B LED strip and receives commands from the Raspberry Pi.

## Requirements

- ESP32 development board
- Arduino IDE or PlatformIO
- FastLED library

## Building

1. Open `ESP32/hockey_stick_light_controller.ino` in Arduino IDE
2. Install FastLED library (Sketch → Include Library → Manage Libraries)
3. Select board: ESP32 Dev Module
4. Upload to ESP32

## Pin Configuration

| Pin | Function |
|-----|----------|
| GPIO 4 | LED Data Out |
| GPIO 16 (RX2) | Serial RX from Raspberry Pi |
| GPIO 17 (TX2) | Serial TX to Raspberry Pi |

## Serial Protocol

The ESP32 listens on Serial2 at 115200 baud:

| Command | Format | Description |
|---------|--------|-------------|
| Celebrate | `C:RRGGBB,RRGGBB,...\n` | Trigger goal animation with hex colors |
| Idle | `I\n` | Stop animation and clear strip |
| Ping | `P\n` | Health check, responds with `PONG\n` |

Example: `C:FFFFFF,002D62,E51937\n` (Washington Capitals colors)

---

# Hardware Setup

## Components

- **Raspberry Pi Zero 2 W** - Runs the Python service
- **ESP32** - Controls LED strip via serial
- **WS2812B LED Strip** - 300+ addressable LEDs
- **5V Power Supply** - Minimum 2A (more for full strip)
- **Momentary Push Button** - For Bluetooth pairing

## Wiring Diagram

### Raspberry Pi ↔ ESP32

| Raspberry Pi | ESP32 | Purpose |
|--------------|-------|---------|
| GPIO 14 (TX) | GPIO 16 (RX2) | Serial data |
| GPIO 27 | EN | ESP32 reset (optional) |
| GND | GND | Common ground |

### ESP32 ↔ LED Strip

| ESP32 | LED Strip | Purpose |
|-------|-----------|---------|
| GPIO 4 | Data In (via 470Ω resistor) | LED control |
| VIN | 5V | Power |
| GND | GND | Ground |

### Pairing Button

| Raspberry Pi | Button |
|--------------|--------|
| GPIO 17 | Pin 1 (uses internal pull-up) |
| GND | Pin 2 |

Press and hold for 3 seconds to enter pairing mode.

## Hardware Protection

- **1000µF Capacitor** - Across 5V/GND rails near power input
- **470Ω Resistor** - Between ESP32 GPIO 4 and LED Data In
- **Logic Level Shifter** (optional) - 74AHCT125 for long cable runs

---

# Build System

Use the Makefile for all build and test operations:

```bash
make help
```

## Available Targets

| Target | Description |
|--------|-------------|
| `make android-build` | Build Android debug APK |
| `make android-release` | Build Android release APK |
| `make android-install` | Install APK to connected device |
| `make android-clean` | Clean Android build artifacts |
| `make python-test` | Run Python unit tests |
| `make python-test-cov` | Run tests with coverage |
| `make python-install` | Install Python package |
| `make python-clean` | Clean Python artifacts |
| `make all` | Build everything |
| `make test` | Run all tests |
| `make clean` | Clean all artifacts |

---

# NHL Team Abbreviations

| Conference | Teams |
|------------|-------|
| Eastern | BOS, BUF, CAR, CBJ, DET, FLA, MTL, NJD, NYI, NYR, OTT, PHI, PIT, TBL, TOR, WSH |
| Western | ANA, ARI, CGY, CHI, COL, DAL, EDM, LAK, MIN, NSH, SEA, SJS, STL, VAN, VGK, WPG |

---

# License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

# Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request