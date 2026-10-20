import logging
import re
import shutil
import subprocess
import time
from pathlib import Path

from .bluetooth_server import clear_paired_devices
from .system_files import remove_system_path
from .wifi_config import clear_wpa_supplicant_networks, WPA_SUPPLICANT_CONF

log = logging.getLogger(__name__)

CONFIG_PATH = Path("/etc/goalstick/config.json")
BT_LIB_PATH = Path("/var/lib/bluetooth")

# Bluetooth device addresses: six colon-separated hex octets.
_BT_ADDR_RE = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")


def factory_reset(led_controller=None) -> bool:
    """
    Perform a factory reset:
    - Clear all Bluetooth pairings
    - Remove WiFi configuration
    - Delete GoalStick config

    Returns True if successful.
    """
    log.warning("FACTORY RESET initiated!")

    # Flash red to indicate factory reset starting
    if led_controller and led_controller.is_connected():
        try:
            led_controller._send_command("C:FF0000")
            time.sleep(2)  # Show red for 2 seconds
        except Exception as e:
            log.warning(f"Could not send factory reset LED indicator: {e}")

    success = True

    # 1. Clear Bluetooth pairings
    if not _clear_bluetooth_pairings():
        success = False

    # 2. Clear WiFi configuration
    if not _clear_wifi_config():
        success = False

    # 3. Delete GoalStick config
    if not _clear_goalstick_config():
        success = False

    if success:
        log.info("Factory reset complete!")
    else:
        log.error("Factory reset completed with errors")

    return success


def _is_bt_address_name(name: str) -> bool:
    return bool(_BT_ADDR_RE.match(name.upper()))


def _clear_bluetooth_pairings() -> bool:
    """Remove all paired Bluetooth devices."""
    try:
        log.info("Clearing Bluetooth pairings...")

        clear_paired_devices()

        # Also clear BlueZ's on-disk cache so pairings are truly gone even if
        # bluetoothctl failed. Only real (non-symlink) directories whose names
        # are Bluetooth addresses, nested under an adapter directory that is
        # also named by address, are touched.
        if BT_LIB_PATH.is_dir() and not BT_LIB_PATH.is_symlink():
            for adapter_dir in BT_LIB_PATH.iterdir():
                if adapter_dir.is_symlink() or not adapter_dir.is_dir():
                    continue
                if not _is_bt_address_name(adapter_dir.name):
                    continue
                for item in adapter_dir.iterdir():
                    if item.is_symlink() or not item.is_dir():
                        continue
                    if not _is_bt_address_name(item.name):
                        continue
                    log.info(f"Removing Bluetooth cache: {item}")
                    if not remove_system_path(item):
                        log.warning(f"Could not remove {item}")

        # Restart Bluetooth service to apply changes
        log.info("Restarting Bluetooth service...")
        subprocess.run(
            ["sudo", "systemctl", "restart", "bluetooth"],
            capture_output=True,
            text=True,
            timeout=30
        )

        log.info("Bluetooth pairings cleared")
        return True

    except Exception as e:
        log.error(f"Error clearing Bluetooth pairings: {e}")
        return False


def _clear_wifi_config() -> bool:
    """Remove WiFi configuration."""
    try:
        log.info("Clearing WiFi configuration...")

        if shutil.which("nmcli"):
            # Get all WiFi connections and delete them by UUID (names can
            # contain ':' which would break name-based parsing).
            result = subprocess.run(
                ["nmcli", "-t", "-f", "UUID,TYPE,NAME", "connection", "show"],
                capture_output=True,
                text=True,
                timeout=10
            )

            for line in result.stdout.strip().split('\n'):
                parts = line.split(':', 2)
                if len(parts) >= 2 and parts[1] == '802-11-wireless':
                    conn_uuid = parts[0]
                    conn_name = parts[2] if len(parts) > 2 else conn_uuid
                    log.info(f"Removing WiFi connection: {conn_name}")
                    subprocess.run(
                        ["sudo", "nmcli", "connection", "delete", "uuid", conn_uuid],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )

            log.info("WiFi configuration cleared (NetworkManager)")
            return True

        # Fall back to wpa_supplicant
        if WPA_SUPPLICANT_CONF.exists():
            if not clear_wpa_supplicant_networks():
                return False

            subprocess.run(
                ["sudo", "wpa_cli", "-i", "wlan0", "reconfigure"],
                capture_output=True,
                text=True,
                timeout=10
            )

            log.info("WiFi configuration cleared (wpa_supplicant)")
            return True

        log.info("No WiFi configuration found to clear")
        return True

    except Exception as e:
        log.error(f"Error clearing WiFi configuration: {e}")
        return False


def _clear_goalstick_config() -> bool:
    """Delete GoalStick configuration file."""
    try:
        log.info("Clearing GoalStick configuration...")

        if CONFIG_PATH.exists():
            CONFIG_PATH.unlink()
            log.info(f"Deleted {CONFIG_PATH}")
        else:
            log.info("No GoalStick config file to delete")

        return True

    except Exception as e:
        log.error(f"Error clearing GoalStick config: {e}")
        return False
