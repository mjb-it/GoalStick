# GoalStick Python Service

Python service for monitoring NHL games and triggering LED celebrations on a Raspberry Pi.

## Features

- Monitors NHL API for live game scores
- Triggers LED celebration when your team scores
- Bluetooth configuration via Android app
- Auto-updates code and system security patches
- Factory reset via 10-second button hold

## Hardware Requirements

- Raspberry Pi Zero 2W (or any Pi with WiFi/Bluetooth)
- ESP32 for LED control (connected via UART)
- Momentary push button (for pairing/reset)
- WS2812B LED strip

## Wiring

### Pi Zero 2W → ESP32

| Pi Zero 2W Pin | Function | ESP32 Pin |
|----------------|----------|-----------|
| GPIO 14 (TXD)  | UART TX  | RX (GPIO 3) |
| GPIO 15 (RXD)  | UART RX  | TX (GPIO 1) |
| GPIO 27        | Reset    | EN |
| GND            | Ground   | GND |
| 5V             | Power    | VIN |

### Button (Pairing/Reset)

| Pi Zero 2W Pin | Function |
|----------------|----------|
| GPIO 17        | Button (one side) |
| GND            | Button (other side) |

- **Hold 3 seconds**: Enter Bluetooth pairing mode
- **Hold 10 seconds**: Factory reset (clears WiFi, Bluetooth, config)

### Status LED (RGB, Common Cathode)

| Pi Zero 2W Pin | Function | LED Pin |
|----------------|----------|---------|
| GPIO 22        | Red      | R (via resistor) |
| GPIO 23        | Green    | G (via resistor) |
| GPIO 24        | Blue     | B (via resistor) |
| GND            | Ground   | Common Cathode |

Use high-value resistors (1kΩ+) to keep the LED dim.

**LED States** (LED is off during normal operation):

| Color | Pattern | Meaning |
|-------|---------|---------|
| Off | - | Normal operation |
| Yellow | Solid | Booting |
| Blue | Slow blink | Bluetooth pairing mode |
| Cyan | Slow blink | Updating |
| Red | Solid | Error |
| Red | Fast blink | No network connectivity |

## Installation

### Prerequisites

Install system dependencies (required for D-Bus and GPIO):

```bash
sudo apt-get update
sudo apt-get install -y python3-gi python3-dbus bluetooth bluez
```

Enable Bluetooth compatibility mode for SPP:

```bash
sudo sed -i 's/ExecStart=\/usr\/libexec\/bluetooth\/bluetoothd/ExecStart=\/usr\/libexec\/bluetooth\/bluetoothd -C/' /lib/systemd/system/bluetooth.service
sudo systemctl daemon-reload
sudo systemctl restart bluetooth
```

### Quick Deploy (Production)

Clone and deploy to `/opt/goalstick`:

```bash
git clone https://github.com/mjb-it/GoalStick.git ~/GoalStick
cd ~/GoalStick
make deploy
```

This will:
1. Copy files to `/opt/goalstick`
2. Create virtual environment with system packages
3. Install Python dependencies
4. Set up and start the systemd service

### Development Install

For development on the Pi:

```bash
git clone https://github.com/mjb-it/GoalStick.git ~/GoalStick
cd ~/GoalStick
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install -e "PythonSrc[dev]"
make service-install
```

## Configuration

Configuration is stored in `/etc/goalstick/config.json`:

```json
{
  "team_abbr": "WSH"
}
```

Configure via the Android app or manually edit the file.

## Service Management

```bash
# Check status
make service-status

# View logs
make service-logs

# Restart service
sudo systemctl restart goalstick

# Stop service
sudo systemctl stop goalstick

# Uninstall service
make service-uninstall
```

## File Locations

| Path | Description |
|------|-------------|
| `/opt/goalstick` | Application code (production) |
| `/etc/goalstick/config.json` | Configuration file |
| `/var/log/goalstick/goalstick.log` | Log file (rotates weekly) |

## Manual Usage

For testing without the service:

```bash
cd /opt/goalstick/PythonSrc
source ../.venv/bin/activate

# Normal operation (monitors games)
python main.py

# Specify team
python main.py --team WSH

# Enter pairing mode
python main.py --pair

# Show current team
python main.py --show-team
```

## Auto-Updates

The service automatically:
- **Daily (8 AM)**: Checks for code updates via `git pull`
- **Weekly (Sundays)**: Runs system security updates

## Read-Only Filesystem (Optional)

For production devices, you can enable a read-only root filesystem to protect the SD card from corruption due to power loss:

```bash
make deploy-readonly
sudo reboot
```

This sets up:
- **Overlay filesystem** - Root is read-only, changes go to RAM
- **Persistent storage** - Config, WiFi, and Bluetooth survive reboots
- **tmpfs logs** - Logs are in RAM (lost on reboot, but viewable via `journalctl`)

### Persistent Data Locations

| Data | Location |
|------|----------|
| GoalStick config | `/persistent/goalstick/` |
| Bluetooth pairings | `/persistent/bluetooth/` |
| WiFi credentials | `/persistent/wpa_supplicant/` |

### Helper Commands

```bash
goalstick-status  # Check if overlay is active
goalstick-rw      # Instructions to disable overlay for manual changes
goalstick-ro      # Re-enable overlay after changes
```

### How Updates Work with Read-Only Root

When updates are available:
1. Service detects update, disables overlay, reboots
2. On reboot (read-write mode), applies update, re-enables overlay, reboots
3. On final reboot, system is back to read-only with updates applied

## Troubleshooting

### Service won't start

```bash
# Check status and recent logs
sudo systemctl status goalstick
sudo journalctl -u goalstick -n 50

# Reset failed state
sudo systemctl reset-failed goalstick
sudo systemctl start goalstick
```

### Bluetooth pairing issues

```bash
# Check Bluetooth status
sudo systemctl status bluetooth
bluetoothctl show

# Restart Bluetooth
sudo systemctl restart bluetooth
```

### ESP32 not responding

The service will attempt to reset the ESP32 automatically. Check wiring if issues persist.

## License

MIT
