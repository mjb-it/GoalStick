import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

CONFIG_PATH = Path("/etc/goalstick/config.json")


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
            import time
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


def _clear_bluetooth_pairings() -> bool:
    """Remove all paired Bluetooth devices."""
    try:
        log.info("Clearing Bluetooth pairings...")
        
        # Get list of paired devices
        result = subprocess.run(
            ["bluetoothctl", "paired-devices"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            log.warning("Could not list paired devices")
        else:
            # Parse device addresses and remove each one
            for line in result.stdout.strip().split('\n'):
                if line.startswith("Device "):
                    parts = line.split()
                    if len(parts) >= 2:
                        mac_address = parts[1]
                        log.info(f"Removing paired device: {mac_address}")
                        subprocess.run(
                            ["bluetoothctl", "remove", mac_address],
                            capture_output=True,
                            text=True,
                            timeout=10
                        )
        
        # Also clear the Bluetooth device cache directory directly
        # This ensures pairings are truly removed even if bluetoothctl fails
        bt_lib_path = Path("/var/lib/bluetooth")
        if bt_lib_path.exists():
            for adapter_dir in bt_lib_path.iterdir():
                if adapter_dir.is_dir():
                    for item in adapter_dir.iterdir():
                        # Skip the adapter's own settings file
                        if item.name == "settings":
                            continue
                        # Remove paired device directories (MAC address format)
                        if item.is_dir() and ":" in item.name:
                            log.info(f"Removing Bluetooth cache: {item}")
                            subprocess.run(
                                ["sudo", "rm", "-rf", str(item)],
                                capture_output=True,
                                text=True
                            )
        
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
        
        # Try NetworkManager first
        result = subprocess.run(
            ["which", "nmcli"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            # Get all WiFi connections and delete them
            result = subprocess.run(
                ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            for line in result.stdout.strip().split('\n'):
                if ':802-11-wireless' in line:
                    conn_name = line.split(':')[0]
                    log.info(f"Removing WiFi connection: {conn_name}")
                    subprocess.run(
                        ["sudo", "nmcli", "connection", "delete", conn_name],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
            
            log.info("WiFi configuration cleared (NetworkManager)")
            return True
        
        # Fall back to wpa_supplicant
        wpa_conf = Path("/etc/wpa_supplicant/wpa_supplicant.conf")
        if wpa_conf.exists():
            # Write minimal config (no networks)
            minimal_config = """ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=US

"""
            # Write to temp file and copy with sudo
            temp_file = Path("/tmp/wpa_supplicant.conf.tmp")
            temp_file.write_text(minimal_config)
            
            subprocess.run(
                ["sudo", "cp", str(temp_file), str(wpa_conf)],
                capture_output=True,
                text=True
            )
            temp_file.unlink()
            
            # Reconfigure wlan0
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
