"""
Bluetooth RFCOMM (SPP) servers for the Android app.

Two servers share one implementation:

* `BluetoothServer` - pairing mode. Started by a physical button hold (or
  `main.py --pair`). The adapter is made discoverable for a limited time and
  WiFi credentials are accepted. This is the only path that can change WiFi.
* `BluetoothCommandServer` - background mode. Runs while the service is up so
  the app can read config, change team/delay and fire a test celebration.
  WiFi changes are refused here.

Wire protocol
-------------
Each message is one JSON object. Messages SHOULD be newline-terminated; the
server also accepts bare, back-to-back JSON objects for compatibility with
older app versions, and handles fragmentation across reads. Every response is
a JSON object followed by "\\n".

Request types: "ping", "get_config", "test_goal", "config".
Responses always carry "status": "ok" | "error" and, on error, "message".

Transport security
------------------
The sockets use BT_SECURITY_LOW to match the app's insecure RFCOMM socket:
on a headless device Just Works pairing is the only option, and bonding has
proven unreliable (see git history). Physical access to the button is the
gate for WiFi changes; the background server limits itself to low-impact
operations and validates everything it receives.
"""

import json
import logging
import socket
import struct
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from .config_store import ConfigStore, normalize_team_abbr, clamp_delay

# Bluetooth socket security levels (from Linux kernel bluetooth.h)
_SOL_BLUETOOTH = 274
_BT_SECURITY = 4
_BT_SECURITY_LOW = 1
_BT_SECURITY_LOW_OPT = struct.pack('BB', _BT_SECURITY_LOW, 0)

log = logging.getLogger(__name__)

# Bluetooth SPP UUID
SPP_UUID = "00001101-0000-1000-8000-00805F9B34FB"

# Protocol limits
MAX_MESSAGE_BYTES = 4096        # A single JSON message may not exceed this
RECV_CHUNK_BYTES = 1024
TEST_GOAL_MIN_INTERVAL = 3.0    # Seconds between test celebrations
MAX_MESSAGES_PER_CONNECTION = 200


@dataclass
class ReceivedConfig:
    wifi_ssid: str
    wifi_password: str
    team_abbr: str


@dataclass
class BluetoothServerConfig:
    device_name: str = None  # Will use hostname if None
    timeout: int = 180  # 3 minutes
    channel: int = 1


# ---------------------------------------------------------------------------
# Message framing
# ---------------------------------------------------------------------------

class FramingError(Exception):
    """The peer sent something that cannot be recovered from; drop the connection."""


class MessageFramer:
    """
    Accumulates bytes from a stream and yields complete JSON objects.

    Accepts newline-delimited JSON (preferred) and bare concatenated objects
    (legacy). Partial messages are buffered until complete. The buffer is
    capped so a misbehaving client cannot grow memory without bound.
    """

    def __init__(self, max_message_bytes: int = MAX_MESSAGE_BYTES):
        self._buf = bytearray()
        self._max = max_message_bytes
        self._decoder = json.JSONDecoder()

    def feed(self, chunk: bytes) -> List[dict]:
        self._buf.extend(chunk)
        messages: List[dict] = []

        while self._buf:
            try:
                text = bytes(self._buf).decode("utf-8")
            except UnicodeDecodeError as e:
                # A multi-byte character may be split across reads.
                if e.start >= len(self._buf) - 3:
                    break
                raise FramingError("invalid UTF-8") from e

            stripped = text.lstrip()
            if not stripped:
                self._buf.clear()
                break

            try:
                obj, end = self._decoder.raw_decode(stripped)
            except json.JSONDecodeError:
                newline = stripped.find("\n")
                if newline != -1:
                    # A complete line that is not JSON: discard it and go on.
                    log.warning("Discarding non-JSON line from client")
                    self._buf = bytearray(stripped[newline + 1:].encode("utf-8"))
                    continue
                if len(self._buf) > self._max:
                    raise FramingError("message exceeds maximum size")
                break  # incomplete; wait for more bytes

            self._buf = bytearray(stripped[end:].encode("utf-8"))
            if isinstance(obj, dict):
                messages.append(obj)
            else:
                log.warning(f"Ignoring non-object JSON message: {type(obj).__name__}")

        if len(self._buf) > self._max:
            raise FramingError("message exceeds maximum size")
        return messages


def encode_response(obj: dict) -> bytes:
    return (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# Command handling (shared by both servers)
# ---------------------------------------------------------------------------

class CommandHandler:
    """
    Validates and executes app commands. Has no socket knowledge, so it is
    easy to unit test.
    """

    def __init__(self, led_controller=None, config_store: Optional[ConfigStore] = None,
                 allow_wifi: bool = False,
                 on_config_received: Optional[Callable[[ReceivedConfig], None]] = None):
        self.led_controller = led_controller
        self.config_store = config_store or ConfigStore()
        self.allow_wifi = allow_wifi
        self.on_config_received = on_config_received
        self._last_test_goal = 0.0
        self.last_received_config: Optional[ReceivedConfig] = None

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _get_ip_address() -> Optional[str]:
        """Get the current IPv4 address of wlan0."""
        try:
            result = subprocess.run(
                ["ip", "-4", "addr", "show", "wlan0"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'inet ' in line:
                        return line.strip().split()[1].split('/')[0]
        except Exception:
            pass
        return None

    def _current_config(self) -> dict:
        config = self.config_store.load()
        return {
            "team_abbr": config.team_abbr,
            "celebration_delay_seconds": config.celebration_delay_seconds,
            "ip_address": self._get_ip_address(),
        }

    def _team_is_known(self, team: str) -> bool:
        """If team colors are loaded, the team must be one we can light up."""
        known = getattr(self.led_controller, "known_teams", None)
        if callable(known):
            teams = known()
            if teams:
                return team in teams
        return True

    @staticmethod
    def _error(message: str) -> dict:
        return {"status": "error", "message": message}

    # -- commands ---------------------------------------------------------

    def handle(self, message: dict) -> dict:
        msg_type = message.get("type")
        if not isinstance(msg_type, str):
            return self._error("missing type")

        handler = {
            "ping": self._handle_ping,
            "get_config": self._handle_get_config,
            "test_goal": self._handle_test_goal,
            "config": self._handle_config,
        }.get(msg_type)

        if handler is None:
            log.warning(f"Unknown message type: {msg_type!r}")
            return self._error("unknown type")

        try:
            return handler(message)
        except Exception as e:
            log.exception(f"Error handling {msg_type} message")
            return self._error(f"internal error: {type(e).__name__}")

    def _handle_ping(self, _message: dict) -> dict:
        return {"status": "ok", "type": "pong"}

    def _handle_get_config(self, _message: dict) -> dict:
        return {"status": "ok", "config": self._current_config()}

    def _handle_test_goal(self, _message: dict) -> dict:
        now = time.monotonic()
        if now - self._last_test_goal < TEST_GOAL_MIN_INTERVAL:
            return self._error("too many test requests")
        self._last_test_goal = now

        if not self.led_controller:
            return self._error("LED controller unavailable")

        team = self.config_store.get_team()
        log.info(f"Triggering test goal celebration for {team}")
        if not self.led_controller.celebrate(team):
            return self._error("LED controller did not accept the command")
        return {"status": "ok"}

    def _handle_config(self, message: dict) -> dict:
        # --- validate -----------------------------------------------------
        team_raw = message.get("team_abbr")
        team: Optional[str] = None
        if team_raw is not None:
            team = normalize_team_abbr(team_raw)
            if team is None:
                return self._error("invalid team_abbr")
            if not self._team_is_known(team):
                return self._error(f"unknown team {team}")

        delay_raw = message.get("celebration_delay_seconds")
        delay: Optional[int] = None
        if delay_raw is not None:
            if isinstance(delay_raw, bool) or not isinstance(delay_raw, (int, float, str)):
                return self._error("invalid celebration_delay_seconds")
            try:
                delay = clamp_delay(int(delay_raw))
            except (TypeError, ValueError):
                return self._error("invalid celebration_delay_seconds")

        ssid = message.get("wifi_ssid") or ""
        password = message.get("wifi_password") or ""
        if not (isinstance(ssid, str) and isinstance(password, str)):
            return self._error("invalid wifi credentials")
        # Older app versions always include the phone's current SSID even when
        # the user only wants to change the team. Treat WiFi as requested only
        # when a password was supplied.
        wants_wifi = bool(password)
        if ssid and not password:
            log.info("Ignoring wifi_ssid without a password")
        if wants_wifi and not ssid:
            return self._error("wifi_ssid is required with wifi_password")
        if wants_wifi and not self.allow_wifi:
            return self._error("wifi configuration requires pairing mode")

        log.info(f"Received config - Team: {team}, Delay: {delay}, WiFi: {'yes' if wants_wifi else 'no'}")

        # --- apply --------------------------------------------------------
        if team is not None or delay is not None:
            if not self.config_store.update(team_abbr=team, celebration_delay_seconds=delay):
                return self._error("failed to save configuration")

        wifi_result = "skipped"
        if wants_wifi:
            from .wifi_config import configure_wifi, validate_ssid, validate_passphrase, WifiValidationError
            try:
                validate_ssid(ssid)
                validate_passphrase(password)
            except WifiValidationError as e:
                return self._error(f"invalid wifi credentials: {e}")

            if configure_wifi(ssid, password):
                log.info(f"WiFi configured for network: {ssid}")
                wifi_result = "ok"
            else:
                log.warning(f"Failed to configure WiFi for network: {ssid}")
                wifi_result = "failed"

        received = ReceivedConfig(
            wifi_ssid=ssid if wants_wifi else "",
            wifi_password=password if wants_wifi else "",
            team_abbr=team or self.config_store.get_team(),
        )
        self.last_received_config = received
        if self.on_config_received:
            try:
                self.on_config_received(received)
            except Exception:
                log.exception("Config callback failed")

        if wifi_result == "failed":
            return self._error("wifi configuration failed - check the network name and password")
        return {"status": "ok", "wifi": wifi_result}


# ---------------------------------------------------------------------------
# Adapter helpers (shared)
# ---------------------------------------------------------------------------

def _run_command(cmd: list, timeout: int = 10) -> Tuple[bool, str]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except Exception as e:
        return False, str(e)


def _ensure_adapter_up(attempts: int = 3) -> bool:
    """Unblock rfkill and bring hci0 up. Returns True if the adapter is running."""
    _run_command(["sudo", "rfkill", "unblock", "bluetooth"])
    time.sleep(0.5)
    for attempt in range(attempts):
        _run_command(["sudo", "hciconfig", "hci0", "up"])
        _run_command(["sudo", "bluetoothctl", "power", "on"])
        time.sleep(0.5)
        _, status = _run_command(["hciconfig", "hci0"])
        if "UP RUNNING" in status:
            log.info("Bluetooth adapter is up and running")
            return True
        log.warning(f"Attempt {attempt + 1} to bring up hci0 failed, retrying...")
        time.sleep(1)
    log.error(f"Failed to bring up Bluetooth adapter after {attempts} attempts")
    return False


def _set_scan_mode(discoverable: bool) -> None:
    """piscan = connectable + discoverable; pscan = connectable only."""
    mode = "piscan" if discoverable else "pscan"
    ok, output = _run_command(["sudo", "hciconfig", "hci0", mode])
    if not ok:
        log.warning(f"hciconfig {mode} failed: {output.strip()}")
    _run_command(["bluetoothctl", "discoverable", "on" if discoverable else "off"])
    _run_command(["bluetoothctl", "pairable", "on" if discoverable else "off"])


def _set_device_name(name: str) -> None:
    _run_command(["bluetoothctl", "system-alias", name])
    _run_command(["sudo", "hciconfig", "hci0", "name", name])


def _set_device_class() -> None:
    # "Computer - Uncategorized" with NO service classes so Android does not
    # treat us as an audio device.
    _run_command(["sudo", "hciconfig", "hci0", "class", "0x000100"])


def _get_local_bluetooth_address() -> Optional[str]:
    ok, output = _run_command(["hciconfig", "hci0"])
    if ok:
        for line in output.split('\n'):
            if 'BD Address:' in line:
                parts = line.split('BD Address:')
                if len(parts) > 1:
                    return parts[1].strip().split()[0]
    ok, output = _run_command(["bluetoothctl", "show"])
    if ok:
        for line in output.split('\n'):
            if line.startswith('Controller'):
                parts = line.split()
                if len(parts) >= 2:
                    return parts[1]
    return None


def _register_sdp_service(channel: int) -> None:
    ok, output = _run_command(["sudo", "sdptool", "add", "--channel", str(channel), "SP"])
    if ok:
        log.info(f"Registered SPP service on channel {channel}")
    else:
        log.warning(f"sdptool add failed (continuing): {output.strip()}")


def _create_server_socket(channel: int, accept_timeout: float) -> socket.socket:
    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # Accept insecure connections to match Android's
    # createInsecureRfcommSocketToServiceRecord (see module docstring).
    sock.setsockopt(_SOL_BLUETOOTH, _BT_SECURITY, _BT_SECURITY_LOW_OPT)
    sock.settimeout(accept_timeout)

    local_addr = _get_local_bluetooth_address()
    if not local_addr:
        sock.close()
        raise RuntimeError("Could not find local Bluetooth adapter address")

    log.info(f"Binding to Bluetooth address: {local_addr} channel {channel}")
    sock.bind((local_addr, channel))
    sock.listen(1)
    return sock


def _serve_client(client_socket: socket.socket, handler: CommandHandler,
                  idle_timeout: float, keep_running: Callable[[], bool]) -> None:
    """Read messages from one client until it disconnects, idles out, or misbehaves."""
    client_socket.settimeout(idle_timeout)
    framer = MessageFramer()
    handled = 0

    try:
        while keep_running():
            try:
                chunk = client_socket.recv(RECV_CHUNK_BYTES)
            except socket.timeout:
                log.info("Bluetooth client idle timeout")
                return
            if not chunk:
                return

            try:
                messages = framer.feed(chunk)
            except FramingError as e:
                log.warning(f"Dropping Bluetooth client: {e}")
                try:
                    client_socket.sendall(encode_response({"status": "error", "message": str(e)}))
                except OSError:
                    pass
                return

            for message in messages:
                handled += 1
                if handled > MAX_MESSAGES_PER_CONNECTION:
                    log.warning("Dropping Bluetooth client: too many messages")
                    return
                log.debug(f"Bluetooth message: {message.get('type')}")
                response = handler.handle(message)
                client_socket.sendall(encode_response(response))
    except (OSError, ConnectionError) as e:
        log.warning(f"Bluetooth client connection error: {e}")


# ---------------------------------------------------------------------------
# Pairing-mode server
# ---------------------------------------------------------------------------

class BluetoothServer:
    """Bluetooth RFCOMM server for receiving configuration from the Android app."""

    DATA_TIMEOUT = 300  # Seconds a connected client may stay idle

    def __init__(self, config: BluetoothServerConfig = None, led_controller=None):
        self.config = config or BluetoothServerConfig()
        if self.config.device_name is None:
            self.config.device_name = socket.gethostname()
        self.led_controller = led_controller
        self._running = False
        self._server_socket: Optional[socket.socket] = None
        self._client_socket: Optional[socket.socket] = None
        self._on_config_received: Optional[Callable[[ReceivedConfig], None]] = None

    def set_config_callback(self, callback: Callable[[ReceivedConfig], None]) -> None:
        """Set callback to be called when configuration is received."""
        self._on_config_received = callback

    def _send_led_status(self, colors: list) -> None:
        if self.led_controller and self.led_controller.is_connected():
            self.led_controller._send_command("C:" + ",".join(colors))

    def _setup_bluetooth(self) -> bool:
        """Configure the adapter for pairing: up, named, discoverable."""
        _ensure_adapter_up()
        _set_device_class()
        # Stop PulseAudio so no audio profiles get advertised.
        _run_command(["sudo", "killall", "pulseaudio"])
        _set_device_name(self.config.device_name)
        _set_scan_mode(discoverable=True)

        _, output = _run_command(["hciconfig", "hci0"])
        if "PSCAN" in output and "ISCAN" in output:
            log.info(f"Bluetooth configured as '{self.config.device_name}' - discoverable and connectable")
        else:
            log.warning(f"Bluetooth may not be fully discoverable. hciconfig output: {output}")
        return True

    def start(self) -> Optional[ReceivedConfig]:
        """
        Start the pairing server and wait for configuration.

        Clients are accepted until `config.timeout` elapses. Returns the last
        configuration received, or None if none arrived.
        """
        log.info("Starting Bluetooth configuration server")
        self._running = True

        if self.led_controller:
            self.led_controller.connect()

        handler = CommandHandler(
            led_controller=self.led_controller,
            config_store=ConfigStore(),
            allow_wifi=True,
            on_config_received=self._on_config_received,
        )

        try:
            self._setup_bluetooth()
            _register_sdp_service(self.config.channel)
            self._send_led_status(["0000FF"])  # Blue - waiting for connection

            deadline = time.monotonic() + self.config.timeout
            self._server_socket = _create_server_socket(self.config.channel, accept_timeout=5)
            log.info(f"Listening for Bluetooth connections on channel {self.config.channel}")

            while self._running and time.monotonic() < deadline:
                try:
                    self._client_socket, client_info = self._server_socket.accept()
                except socket.timeout:
                    continue

                log.info(f"Connected to {client_info}")
                self._send_led_status(["00FFFF"])  # Cyan - connected
                try:
                    _serve_client(self._client_socket, handler, self.DATA_TIMEOUT, lambda: self._running)
                finally:
                    try:
                        self._client_socket.close()
                    except OSError:
                        pass
                    self._client_socket = None

                if handler.last_received_config is not None:
                    self._send_led_status(["00FF00"])  # Green - success
                    return handler.last_received_config
                self._send_led_status(["0000FF"])  # Back to waiting

            if self._running:
                log.warning("Timeout waiting for Bluetooth connection")
                self._send_led_status(["FF0000"])  # Red for timeout
            return handler.last_received_config

        except Exception as e:
            log.error(f"Bluetooth server error: {e}")
            self._send_led_status(["FF0000"])
            return None
        finally:
            self._cleanup()

    def _cleanup(self) -> None:
        self._running = False
        for attr in ("_client_socket", "_server_socket"):
            sock = getattr(self, attr)
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass
                setattr(self, attr, None)

        _set_scan_mode(discoverable=False)

        # Give time for the LED animation
        time.sleep(2)
        if self.led_controller:
            self.led_controller.idle()

    def stop(self) -> None:
        log.info("Stopping Bluetooth server")
        self._running = False
        self._cleanup()

    def is_running(self) -> bool:
        return self._running


# ---------------------------------------------------------------------------
# Background command server
# ---------------------------------------------------------------------------

class BluetoothCommandServer:
    """
    Background Bluetooth server that accepts commands from the Android app
    during normal operation (get_config, test_goal, team/delay changes).
    WiFi changes are refused; they require pairing mode.
    """

    CLIENT_IDLE_TIMEOUT = 60
    BIND_RETRY_SECONDS = 10

    def __init__(self, led_controller=None, config_store: Optional[ConfigStore] = None,
                 channel: int = 1, discoverable: bool = True):
        self.led_controller = led_controller
        self.config_store = config_store or ConfigStore()
        self.channel = channel
        # Discoverable so the app can find the device without a button press.
        # Set False to require pairing mode for discovery (the app must then
        # remember the device address).
        self.discoverable = discoverable
        self._running = False
        self._server_socket: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None

    def _server_loop(self) -> None:
        log.info("Background Bluetooth command server starting...")
        handler = CommandHandler(
            led_controller=self.led_controller,
            config_store=self.config_store,
            allow_wifi=False,
        )

        _ensure_adapter_up()
        _set_scan_mode(discoverable=self.discoverable)
        _register_sdp_service(self.channel)

        try:
            # The channel may still be held briefly after pairing mode, or the
            # adapter may not be ready yet: keep trying while we are running.
            while self._running and self._server_socket is None:
                try:
                    self._server_socket = _create_server_socket(self.channel, accept_timeout=5)
                except (OSError, RuntimeError) as e:
                    log.warning(f"Background BT server could not listen ({e}); retrying in {self.BIND_RETRY_SECONDS}s")
                    for _ in range(self.BIND_RETRY_SECONDS):
                        if not self._running:
                            break
                        time.sleep(1)
            if not self._running:
                return
            log.info(f"Background Bluetooth command server listening on channel {self.channel}")

            while self._running:
                try:
                    client_socket, client_info = self._server_socket.accept()
                except socket.timeout:
                    continue
                except OSError as e:
                    if self._running:
                        log.error(f"Background BT server accept error: {e}")
                    break

                log.info(f"Background BT server: client connected from {client_info}")
                try:
                    _serve_client(client_socket, handler, self.CLIENT_IDLE_TIMEOUT, lambda: self._running)
                finally:
                    try:
                        client_socket.close()
                    except OSError:
                        pass
                    log.info("Background BT server: client disconnected")

        except Exception as e:
            log.error(f"Background BT server error: {e}")
        finally:
            if self._server_socket:
                try:
                    self._server_socket.close()
                except OSError:
                    pass
                self._server_socket = None
            self._running = False
            log.info("Background Bluetooth command server stopped")

    def start(self) -> bool:
        if self._running:
            return True
        self._running = True
        self._thread = threading.Thread(target=self._server_loop, daemon=True, name="BluetoothCommandServer")
        self._thread.start()
        return True

    def stop(self) -> None:
        log.info("Stopping background Bluetooth command server...")
        self._running = False
        if self._server_socket:
            try:
                self._server_socket.close()
            except OSError:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=7.0)

    def is_running(self) -> bool:
        return self._running
