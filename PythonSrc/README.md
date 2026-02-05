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
| GPIO 14 (TXD)  | UART TX  | GPIO 16 (RX2) |
| GPIO 15 (RXD)  | UART RX  | GPIO 17 (TX2) |
| GPIO 27        | Reset    | EN |
| GND            | Ground   | GND |
| 5V             | Power    | VIN |

### ESP32 → LED Strip

| ESP32 Pin | Function | LED Strip |
|-----------|----------|-----------|
| GPIO 4    | Data     | DIN |
| GND       | Ground   | GND |
| VIN (5V)  | Power    | 5V (or external PSU for long strips) |

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
| Magenta | Slow blink | WiFi not configured (needs setup) |
| Blue | Slow blink | Bluetooth pairing mode |
| Cyan | Slow blink | Updating |
| Red | Solid | Error |
| Red | Fast blink | No network connectivity |

## Installation

### Option 1: Pre-Built Image (Easiest)

Use the first-boot script to create a ready-to-distribute image:

1. Flash **Raspberry Pi OS Lite 64-bit** with Raspberry Pi Imager
2. In imager settings (⚙️), configure:
   - Enable SSH
   - Set hostname to `goalstick`
   - Configure your WiFi (temporary, will be wiped)
   - Set username/password
3. After flashing, mount the boot partition and copy the setup script:
   ```bash
   cp scripts/firstboot-setup.sh /Volumes/bootfs/firstboot-setup.sh
   ```
4. Edit `/Volumes/bootfs/cmdline.txt` and add to the **end of the existing line**:
   ```
    systemd.run=/boot/firmware/firstboot-setup.sh systemd.run_success_action=reboot
   ```
5. Eject and boot the Pi
6. Wait ~10 minutes for setup to complete (LED will be yellow, then cyan during update)
7. Pi will reboot with **WiFi wiped** - use the Android app to configure

> **Note**: The first-boot script wipes all WiFi credentials after installation,
> making the image safe to distribute without exposing your network password.

### Option 2: Manual Installation

#### Prerequisites

Install system dependencies (required for D-Bus and GPIO):

```bash
sudo apt-get update
sudo apt-get install -y python3-gi python3-dbus bluetooth bluez
```

Enable UART for ESP32 communication:

```bash
# Add to /boot/firmware/config.txt:
echo "enable_uart=1" | sudo tee -a /boot/firmware/config.txt
sudo reboot
```

Enable Bluetooth compatibility mode for SPP:

```bash
sudo sed -i 's/ExecStart=\/usr\/libexec\/bluetooth\/bluetoothd/ExecStart=\/usr\/libexec\/bluetooth\/bluetoothd -C/' /lib/systemd/system/bluetooth.service
sudo systemctl daemon-reload
sudo systemctl restart bluetooth
```

Disable Bluetooth audio plugins (prevents Android from treating GoalStick as a headset):

```bash
sudo tee -a /etc/bluetooth/main.conf << 'EOF'

# Disable audio plugins - GoalStick is not an audio device
[General]
DisablePlugins = a2dp,avrcp
EOF
sudo systemctl restart bluetooth
```

#### Quick Deploy (Production)

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
