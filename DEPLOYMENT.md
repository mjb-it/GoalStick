# GoalStick Deployment Guide

This guide covers automated deployment and hands-free installation of the GoalStick system.

---

## Build System

Use the Makefile for all build and test operations:

```bash
make help
```

## Available Targets

### Android Targets

| Target | Description |
|--------|-------------|
| `make android-build` | Build Android debug APK |
| `make android-release` | Build Android release APK |
| `make android-install` | Install APK to connected device |
| `make android-clean` | Clean Android build artifacts |

### Python Targets

| Target | Description |
|--------|-------------|
| `make python-venv` | Create virtual environment (if needed) |
| `make python-test` | Run Python unit tests |
| `make python-test-cov` | Run tests with coverage report |
| `make python-install` | Install Python package in dev mode |
| `make python-clean` | Clean Python build artifacts |

### Deployment Targets (run on Pi)

| Target | Description |
|--------|-------------|
| `make deploy` | Deploy to /opt/goalstick and install service |
| `make deploy-readonly` | Deploy + set up read-only filesystem (reboot required) |
| `make service-install` | Install systemd service from current directory |
| `make service-uninstall` | Remove systemd service |
| `make service-status` | Check service status |
| `make service-logs` | Tail the service logs |

### Combined Targets

| Target | Description |
|--------|-------------|
| `make all` | Build everything |
| `make test` | Run all tests |
| `make clean` | Clean all artifacts |

---

## Raspberry Pi Setup

### SD Card Preparation

1. Flash Raspberry Pi OS Lite to an SD card
2. Mount the boot partition and copy the following files from this repo:
   - `config.txt` - Enables USB gadget mode
   - `cmdline.txt` - Loads USB Ethernet module
   - `wpa_supplicant.conf` - WiFi credentials (edit with your network)

3. Create an empty `ssh` file on the boot partition to enable SSH:
   ```bash
   touch /Volumes/bootfs/ssh
   ```

### WiFi Configuration

For newer Raspberry Pi OS versions using cloud-init, edit `network-config` on the boot partition:

```yaml
network:
  version: 2

  wifis:
    wlan0:
      dhcp4: true
      optional: false
      access-points:
        "YourWiFiSSID":
          password: "YourWiFiPassword"
```

### USB Ethernet Gadget Mode

If WiFi isn't working, you can access the Pi directly over USB:

1. Ensure `config.txt` contains under `[all]`:
   ```
   dtoverlay=dwc2
   ```

2. Ensure `cmdline.txt` contains:
   ```
   modules-load=dwc2,g_ether
   ```

3. Connect the Pi's **USB** port (not PWR) to your computer

4. SSH to the Pi:
   ```bash
   ssh pi@raspberrypi.local
   ```

---

## Python Service Installation

### Quick Deploy (Recommended)

On the Raspberry Pi, clone the repo and run the deploy target:

```bash
git clone https://github.com/yourusername/GoalStick.git
cd GoalStick
make deploy
```

This will:
- Install to `/opt/goalstick`
- Create a virtual environment
- Install the systemd service
- Start the service automatically

### Manual Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/GoalStick.git
cd GoalStick

# Create virtual environment and install
make python-venv
make python-install

# Or manually:
cd PythonSrc
pip install -e .
```

### Service Management

```bash
# Install service from current directory
make service-install

# Check status
make service-status

# View logs
make service-logs

# Remove service
make service-uninstall
```

### Read-Only Filesystem (Optional)

For production deployments, enable read-only filesystem to prevent SD card corruption:

```bash
make deploy-readonly
```

This requires a reboot to take effect.

### File Locations

| Path | Description |
|------|-------------|
| `/opt/goalstick` | Installation directory |
| `/etc/goalstick/config.json` | Configuration file |
| `/var/log/goalstick/goalstick.log` | Log file |

---

## ESP32 Firmware

### XIAO ESP32C3

1. Install the **esp32 by Espressif Systems** board package in Arduino IDE
2. Select **Tools → Board → esp32 → XIAO_ESP32C3**
3. Open `ESP32/hockey_stick_light_controller_copy_20260131123701/hockey_stick_light_controller/hockey_stick_light_controller.ino`
4. Upload to the board

### Pin Configuration (XIAO ESP32C3)

| Pin | Function |
|-----|----------|
| D10 (GPIO10) | LED Data Out |
| D7 (GPIO20) | Serial RX from Raspberry Pi |
| D6 (GPIO21) | Serial TX to Raspberry Pi |

### Wiring: Raspberry Pi ↔ XIAO ESP32C3

| Raspberry Pi | XIAO ESP32C3 | Purpose |
|--------------|--------------|---------|
| GPIO 14 (TX) | D7 (RX) | Serial data to ESP32 |
| GPIO 15 (RX) | D6 (TX) | Serial data from ESP32 |
| GND | GND | Common ground |

---

## Android App

### Building

```bash
make android-build
```

### Installing

```bash
# With device connected via USB
make android-install
```

APK location: `Android/app/build/outputs/apk/debug/app-debug.apk`

---

## Troubleshooting

### Pi not connecting to WiFi
- Verify `network-config` YAML syntax (spaces, not tabs)
- Check that SSID and password are correct
- Try USB Ethernet gadget mode for direct access

### ESP32 not responding
- Check serial connections (TX→RX, RX→TX)
- Verify baud rate is 115200
- Test with USB Serial Monitor first

### Bluetooth pairing fails
- Ensure Pi Bluetooth is enabled: `sudo systemctl start bluetooth`
- Check that the Android app has Bluetooth permissions
- Hold pairing button for 3+ seconds
