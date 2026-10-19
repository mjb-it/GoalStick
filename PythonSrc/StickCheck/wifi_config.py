import logging
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

from .system_files import write_system_file

log = logging.getLogger(__name__)

WPA_SUPPLICANT_CONF = Path("/etc/wpa_supplicant/wpa_supplicant.conf")
WPA_SUPPLICANT_CONF_ALT = Path("/etc/wpa_supplicant/wpa_supplicant-wlan0.conf")

# NetworkManager keyfile profile owned by GoalStick. Using one fixed file name
# means a new configuration simply replaces the previous one.
NM_CONNECTIONS_DIR = Path("/etc/NetworkManager/system-connections")
NM_PROFILE_PATH = NM_CONNECTIONS_DIR / "goalstick-wifi.nmconnection"

WIFI_INTERFACE = "wlan0"

_WPA_SUPPLICANT_HEADER = """ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=US
"""

_HEX_PSK_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class WifiValidationError(ValueError):
    """Raised when WiFi credentials fail validation."""


def validate_ssid(ssid: str) -> str:
    """
    Validate an SSID per IEEE 802.11: 1 to 32 bytes of UTF-8 with no control
    characters. Returns the SSID unchanged on success.
    """
    if not isinstance(ssid, str):
        raise WifiValidationError("SSID must be a string")
    if not ssid:
        raise WifiValidationError("SSID is empty")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in ssid):
        raise WifiValidationError("SSID contains control characters")
    if len(ssid.encode("utf-8")) > 32:
        raise WifiValidationError("SSID is longer than 32 bytes")
    return ssid


def validate_passphrase(password: str) -> str:
    """
    Validate a WPA/WPA2 passphrase: either 8 to 63 printable ASCII characters
    or a 64 character hex PSK. Returns the passphrase unchanged on success.
    """
    if not isinstance(password, str):
        raise WifiValidationError("Password must be a string")
    if _HEX_PSK_RE.match(password):
        return password
    if not (8 <= len(password) <= 63):
        raise WifiValidationError("Password must be 8 to 63 characters")
    if any(ord(c) < 0x20 or ord(c) > 0x7E for c in password):
        raise WifiValidationError("Password contains non-printable or non-ASCII characters")
    return password


def _nmcli_available() -> bool:
    return shutil.which("nmcli") is not None


def is_wifi_configured() -> bool:
    """
    Check if WiFi is configured on the system.

    Returns:
        True if WiFi credentials are configured, False otherwise
    """
    try:
        # Check NetworkManager first
        if _nmcli_available():
            result = subprocess.run(
                ["nmcli", "-t", "-f", "TYPE,NAME", "connection", "show"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if line.startswith('802-11-wireless:'):
                        return True

        # Fall back to checking wpa_supplicant.conf
        for conf in (WPA_SUPPLICANT_CONF, WPA_SUPPLICANT_CONF_ALT):
            if conf.exists():
                content = conf.read_text()
                if 'network=' in content and 'ssid=' in content:
                    return True

        return False

    except Exception as e:
        log.debug(f"Error checking WiFi config: {e}")
        return False


def configure_wifi(ssid: str, password: str) -> bool:
    """
    Configure WiFi on the Raspberry Pi.

    Credentials are validated first. The password is never passed on a command
    line or written to a world-readable location.

    Args:
        ssid: The WiFi network name
        password: The WiFi password

    Returns:
        True if configuration was successful, False otherwise
    """
    try:
        validate_ssid(ssid)
        validate_passphrase(password)
    except WifiValidationError as e:
        log.warning(f"Rejected WiFi credentials: {e}")
        return False

    try:
        if _nmcli_available():
            return _configure_with_nmcli(ssid, password)
        return _configure_with_wpa_supplicant(ssid, password)
    except Exception as e:
        log.error(f"Failed to configure WiFi: {e}")
        return False


# ---------------------------------------------------------------------------
# NetworkManager (keyfile) backend
# ---------------------------------------------------------------------------

def _keyfile_escape(value: str) -> str:
    """Escape a string for a GLib key file value."""
    value = value.replace("\\", "\\\\")
    if value.startswith(" "):
        value = "\\s" + value[1:]
    return value


def _keyfile_ssid(ssid: str) -> str:
    """Encode an SSID as an unambiguous keyfile byte list (e.g. 71;111;...;)."""
    return ";".join(str(b) for b in ssid.encode("utf-8")) + ";"


def build_nm_keyfile(ssid: str, password: str, conn_uuid: Optional[str] = None) -> str:
    """Build a NetworkManager keyfile profile for a WPA-PSK network."""
    conn_uuid = conn_uuid or str(uuid.uuid4())
    return (
        "[connection]\n"
        f"id={_keyfile_escape(ssid)}\n"
        f"uuid={conn_uuid}\n"
        "type=wifi\n"
        f"interface-name={WIFI_INTERFACE}\n"
        "autoconnect=true\n"
        "autoconnect-priority=10\n"
        "\n"
        "[wifi]\n"
        "mode=infrastructure\n"
        f"ssid={_keyfile_ssid(ssid)}\n"
        "\n"
        "[wifi-security]\n"
        "key-mgmt=wpa-psk\n"
        f"psk={_keyfile_escape(password)}\n"
        "\n"
        "[ipv4]\n"
        "method=auto\n"
        "\n"
        "[ipv6]\n"
        "method=auto\n"
    )


def _configure_with_nmcli(ssid: str, password: str) -> bool:
    """
    Configure WiFi using a NetworkManager keyfile profile.

    The profile is written with mode 0600 directly into
    /etc/NetworkManager/system-connections, so the PSK never appears in a
    process listing. If activation fails the profile is removed again so the
    device stays in the "WiFi not configured" state and the user can retry.
    """
    conn_uuid = str(uuid.uuid4())
    content = build_nm_keyfile(ssid, password, conn_uuid)

    if not write_system_file(NM_PROFILE_PATH, content, mode=0o600):
        log.error("Failed to write NetworkManager profile")
        return False

    try:
        result = subprocess.run(
            ["sudo", "nmcli", "connection", "reload"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            log.warning(f"nmcli connection reload failed: {result.stderr.strip()}")

        result = subprocess.run(
            ["sudo", "nmcli", "connection", "up", "uuid", conn_uuid],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            log.info(f"WiFi configured successfully using NetworkManager: {ssid}")
            return True

        log.warning(f"NetworkManager could not activate '{ssid}': {result.stderr.strip()}")
    except subprocess.TimeoutExpired:
        log.warning("nmcli timed out while activating the connection")

    _remove_nm_profile(conn_uuid)
    return False


def _remove_nm_profile(conn_uuid: str) -> None:
    """Remove the GoalStick-managed profile after a failed activation."""
    try:
        subprocess.run(
            ["sudo", "nmcli", "connection", "delete", "uuid", conn_uuid],
            capture_output=True, text=True, timeout=15,
        )
    except Exception as e:
        log.debug(f"Could not delete failed NM profile: {e}")


# ---------------------------------------------------------------------------
# wpa_supplicant backend
# ---------------------------------------------------------------------------

def _derive_psk(ssid: str, password: str) -> Optional[str]:
    """
    Derive the 64-hex-char PSK. Uses wpa_passphrase with the passphrase on
    stdin (never argv). A 64 char hex password is already a PSK.
    """
    if _HEX_PSK_RE.match(password):
        return password.lower()

    try:
        result = subprocess.run(
            ["wpa_passphrase", ssid],
            input=password + "\n",
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        log.error("wpa_passphrase not found")
        return None

    if result.returncode != 0:
        log.error(f"wpa_passphrase failed: {result.stderr.strip()}")
        return None

    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("psk=") and _HEX_PSK_RE.match(line[4:]):
            return line[4:].lower()

    log.error("wpa_passphrase did not return a PSK")
    return None


def _split_wpa_conf(content: str) -> Tuple[List[str], List[List[str]]]:
    """
    Split a wpa_supplicant.conf into (header_lines, network_blocks).
    Each network block is the list of its lines including the braces.
    """
    header: List[str] = []
    blocks: List[List[str]] = []
    current: Optional[List[str]] = None
    depth = 0

    for line in content.splitlines():
        stripped = line.strip()
        if current is None:
            if stripped.startswith("network=") and stripped.endswith("{"):
                current = [line]
                depth = 1
            else:
                header.append(line)
        else:
            current.append(line)
            depth += stripped.count("{") - stripped.count("}")
            if depth <= 0:
                blocks.append(current)
                current = None
    if current:
        blocks.append(current)
    return header, blocks


def _block_has_ssid(block: List[str], ssid: str) -> bool:
    quoted = f'ssid="{ssid}"'
    hexed = f"ssid={ssid.encode('utf-8').hex()}"
    for line in block:
        s = line.strip()
        if s == quoted or s.lower() == hexed.lower():
            return True
    return False


def build_wpa_conf(existing: Optional[str], ssid: str, psk_hex: str) -> str:
    """
    Return a new wpa_supplicant.conf with any existing block for `ssid`
    removed and a new block appended. The SSID is written in hex form so
    quotes, backslashes and non-ASCII characters cannot break the file.
    """
    if existing is None or not existing.strip():
        header, blocks = _WPA_SUPPLICANT_HEADER.splitlines(), []
    else:
        header, blocks = _split_wpa_conf(existing)

    blocks = [b for b in blocks if not _block_has_ssid(b, ssid)]

    new_block = [
        "network={",
        f"\tssid={ssid.encode('utf-8').hex()}",
        f"\tpsk={psk_hex}",
        "\tkey_mgmt=WPA-PSK",
        "}",
    ]

    parts = ["\n".join(header).rstrip()]
    for b in blocks:
        parts.append("\n".join(b))
    parts.append("\n".join(new_block))
    return "\n\n".join(parts) + "\n"


def _configure_with_wpa_supplicant(ssid: str, password: str) -> bool:
    """Configure WiFi by rewriting wpa_supplicant.conf atomically with mode 0600."""
    psk = _derive_psk(ssid, password)
    if not psk:
        return False

    try:
        existing = WPA_SUPPLICANT_CONF.read_text() if WPA_SUPPLICANT_CONF.exists() else None
    except OSError as e:
        log.warning(f"Could not read existing wpa_supplicant.conf: {e}")
        existing = None

    new_content = build_wpa_conf(existing, ssid, psk)

    if not write_system_file(WPA_SUPPLICANT_CONF, new_content, mode=0o600):
        return False

    try:
        subprocess.run(
            ["sudo", "wpa_cli", "-i", WIFI_INTERFACE, "reconfigure"],
            capture_output=True, text=True, timeout=10,
        )
    except subprocess.TimeoutExpired:
        log.warning("wpa_cli reconfigure timed out")
    except Exception as e:
        log.warning(f"wpa_cli reconfigure failed: {e}")

    log.info(f"WiFi configured successfully using wpa_supplicant: {ssid}")
    return True


def clear_wpa_supplicant_networks() -> bool:
    """Replace wpa_supplicant.conf with a minimal config containing no networks."""
    return write_system_file(WPA_SUPPLICANT_CONF, _WPA_SUPPLICANT_HEADER + "\n", mode=0o600)
