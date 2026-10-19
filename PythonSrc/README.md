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

### Status Indicator (via LED Strip)

The LED strip is used for status indication. No separate status LED needed.

**LED Strip States** (off during normal operation):

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
| `/etc/goalstick/config.json` | Configuration file (written atomically) |
| `/etc/goalstick/network_watchdog.json` | Network watchdog reboot counter |
| `/etc/goalstick/update-allowed-signers` | Optional: SSH keys allowed to sign updates |
| `/etc/NetworkManager/system-connections/goalstick-wifi.nmconnection` | WiFi profile written during pairing (mode 0600) |
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
- **Daily (8 AM)**: Fast-forwards to the tracked upstream branch and reinstalls the package
- **Weekly (Sundays)**: Runs system security updates

Safeguards:
- Updates are only taken from an `https://` remote and only when upstream is a
  pure fast-forward of the installed commit. Diverged history is refused.
- Optionally, every update can be required to carry a valid SSH commit
  signature. Create `/etc/goalstick/update-allowed-signers` in git's
  allowed-signers format and sign your commits:

  ```bash
  # On the Pi
  echo "you@example.com ssh-ed25519 AAAA...your-public-key" | sudo tee /etc/goalstick/update-allowed-signers

  # On your development machine
  git config gpg.format ssh
  git config user.signingkey ~/.ssh/id_ed25519.pub
  git config commit.gpgsign true
  ```

  While the file is absent, updates are applied unsigned (the default).

## Reliability Behaviour

- **systemd watchdog**: the service pings systemd every 20s from a dedicated
  thread in every mode (normal, waiting for WiFi, pairing). A hung process is
  restarted within 60s.
- **Scheduler**: an unexpected error in the daily cycle is logged with a
  traceback and the cycle retries after 60s instead of exiting.
- **Clock jumps**: long sleeps are taken in 60s chunks against the wall clock,
  so an NTP step after boot does not delay the daily check by a day.
- **Game states**: `FINAL`/`OFF` and postponed/suspended/cancelled games
  (`gameScheduleState` of `PPD`/`SUSP`/`CNCL`) end monitoring immediately.
- **Network watchdog**: after 5 minutes offline the WiFi interface is
  restarted; after 15 minutes the Pi reboots, at most 3 times in a row
  without connectivity returning. Connectivity is probed with ping and a TCP
  connect to the NHL API so ICMP-blocking networks are not misdetected. The
  LED strip blinks red while offline.
- **Config writes** go to a temp file and are renamed into place, so power
  loss cannot truncate `config.json`.

## Bluetooth Protocol

The Android app talks to the Pi over RFCOMM (SPP, channel 1) using one JSON
object per message, newline-terminated. Bare back-to-back objects without a
newline are also accepted for older app versions. Responses are always a
JSON object followed by `
` with `"status": "ok"` or
`"status": "error"` plus `"message"`.

| Type | Direction | Notes |
|------|-----------|-------|
| `ping` | app → Pi | Replies `{"status":"ok","type":"pong"}` |
| `get_config` | app → Pi | Returns `team_abbr`, `celebration_delay_seconds`, `ip_address` |
| `test_goal` | app → Pi | Fires a celebration; rate-limited to one per 3s |
| `config` | app → Pi | `team_abbr`, `celebration_delay_seconds`, and in **pairing mode only** `wifi_ssid`/`wifi_password` |

Validation on the Pi: team abbreviations must be 2-3 letters and present in
`team_colors.json`; delays are clamped to 0-180s; SSIDs must be 1-32 bytes
with no control characters; passphrases must be 8-63 printable ASCII
characters or a 64-hex PSK. Messages over 4 KB or non-UTF-8 data close the
connection.

Two servers share this protocol:
- **Pairing mode** (button hold 3s or `main.py --pair`): adapter is
  discoverable for 3 minutes and WiFi credentials are accepted. This is the
  only path that can change WiFi, so physical access to the button is the gate.
- **Background server** (always on): accepts `ping`, `get_config`,
  `test_goal` and team/delay changes. WiFi fields are refused.

The RFCOMM socket uses `BT_SECURITY_LOW` to match the app's insecure socket;
on a headless Pi Just Works pairing is the only workable option. See the
module docstring in `StickCheck/bluetooth_server.py`.

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
