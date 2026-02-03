import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

WPA_SUPPLICANT_CONF = Path("/etc/wpa_supplicant/wpa_supplicant.conf")


def is_wifi_configured() -> bool:
    """
    Check if WiFi is configured on the system.
    
    Returns:
        True if WiFi credentials are configured, False otherwise
    """
    try:
        # Check NetworkManager first
        result = subprocess.run(
            ["nmcli", "-t", "-f", "TYPE,NAME", "connection", "show"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                if line.startswith('802-11-wireless:'):
                    return True
        
        # Fall back to checking wpa_supplicant.conf
        if WPA_SUPPLICANT_CONF.exists():
            content = WPA_SUPPLICANT_CONF.read_text()
            if 'network=' in content and 'ssid=' in content:
                return True
        
        # Check alternative wpa_supplicant location
        alt_conf = Path("/etc/wpa_supplicant/wpa_supplicant-wlan0.conf")
        if alt_conf.exists():
            content = alt_conf.read_text()
            if 'network=' in content and 'ssid=' in content:
                return True
        
        return False
        
    except Exception as e:
        log.debug(f"Error checking WiFi config: {e}")
        return False


def configure_wifi(ssid: str, password: str) -> bool:
    """
    Configure WiFi on the Raspberry Pi using wpa_supplicant.
    
    Args:
        ssid: The WiFi network name
        password: The WiFi password
        
    Returns:
        True if configuration was successful, False otherwise
    """
    if not ssid:
        log.warning("No SSID provided, skipping WiFi configuration")
        return False
    
    try:
        # Use nmcli if available (newer Raspberry Pi OS)
        if _configure_with_nmcli(ssid, password):
            return True
        
        # Fall back to wpa_supplicant
        return _configure_with_wpa_supplicant(ssid, password)
        
    except Exception as e:
        log.error(f"Failed to configure WiFi: {e}")
        return False


def _configure_with_nmcli(ssid: str, password: str) -> bool:
    """Configure WiFi using NetworkManager (nmcli)."""
    try:
        # Check if nmcli is available
        result = subprocess.run(
            ["which", "nmcli"],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            return False
        
        # Delete existing connection with same name if exists
        subprocess.run(
            ["sudo", "nmcli", "connection", "delete", ssid],
            capture_output=True,
            text=True
        )
        
        # Add new WiFi connection
        result = subprocess.run(
            [
                "sudo", "nmcli", "device", "wifi", "connect", ssid,
                "password", password
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            log.info(f"WiFi configured successfully using nmcli: {ssid}")
            return True
        else:
            log.warning(f"nmcli failed: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        log.warning("nmcli timed out")
        return False
    except Exception as e:
        log.debug(f"nmcli not available or failed: {e}")
        return False


def _configure_with_wpa_supplicant(ssid: str, password: str) -> bool:
    """Configure WiFi using wpa_supplicant.conf."""
    try:
        # Generate PSK using wpa_passphrase
        result = subprocess.run(
            ["wpa_passphrase", ssid, password],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            log.error(f"wpa_passphrase failed: {result.stderr}")
            return False
        
        # Parse the output to get the network block
        network_block = result.stdout
        
        # Read existing wpa_supplicant.conf
        if WPA_SUPPLICANT_CONF.exists():
            existing_content = WPA_SUPPLICANT_CONF.read_text()
        else:
            existing_content = """ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=US

"""
        
        # Check if this network already exists and remove it
        lines = existing_content.split('\n')
        new_lines = []
        skip_until_brace = False
        for line in lines:
            if f'ssid="{ssid}"' in line:
                # Found existing network, skip until closing brace
                # Go back and remove the "network={" line
                while new_lines and 'network={' not in new_lines[-1]:
                    new_lines.pop()
                if new_lines and 'network={' in new_lines[-1]:
                    new_lines.pop()
                skip_until_brace = True
                continue
            if skip_until_brace:
                if '}' in line:
                    skip_until_brace = False
                continue
            new_lines.append(line)
        
        # Add the new network block
        new_content = '\n'.join(new_lines).rstrip() + '\n\n' + network_block
        
        # Write to a temp file and move with sudo
        temp_file = Path("/tmp/wpa_supplicant.conf.tmp")
        temp_file.write_text(new_content)
        
        result = subprocess.run(
            ["sudo", "cp", str(temp_file), str(WPA_SUPPLICANT_CONF)],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            log.error(f"Failed to copy wpa_supplicant.conf: {result.stderr}")
            return False
        
        temp_file.unlink()
        
        # Reconfigure wlan0
        subprocess.run(
            ["sudo", "wpa_cli", "-i", "wlan0", "reconfigure"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        log.info(f"WiFi configured successfully using wpa_supplicant: {ssid}")
        return True
        
    except subprocess.TimeoutExpired:
        log.error("wpa_supplicant configuration timed out")
        return False
    except Exception as e:
        log.error(f"Failed to configure wpa_supplicant: {e}")
        return False
