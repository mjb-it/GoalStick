import json
import logging
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Optional, Callable

from .bluetooth_agent import start_agent, stop_agent

log = logging.getLogger(__name__)

# Bluetooth SPP UUID
SPP_UUID = "00001101-0000-1000-8000-00805F9B34FB"


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


class BluetoothServer:
    """Bluetooth RFCOMM server for receiving configuration from Android app."""
    
    def __init__(self, config: BluetoothServerConfig = None, led_controller=None):
        self.config = config or BluetoothServerConfig()
        # Use hostname as device name if not specified
        if self.config.device_name is None:
            import socket
            self.config.device_name = socket.gethostname()
        self.led_controller = led_controller
        self._running = False
        self._server_socket = None
        self._client_socket = None
        self._on_config_received: Optional[Callable[[ReceivedConfig], None]] = None
    
    def set_config_callback(self, callback: Callable[[ReceivedConfig], None]) -> None:
        """Set callback to be called when configuration is received."""
        self._on_config_received = callback
    
    def _run_command(self, cmd: list) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            return False, str(e)
    
    def _setup_bluetooth(self) -> bool:
        """Configure Bluetooth for pairing."""
        # Unblock Bluetooth via rfkill (required on Pi Zero W 2)
        self._run_command(["sudo", "rfkill", "unblock", "bluetooth"])
        time.sleep(0.5)
        
        # Ensure Bluetooth adapter is up (try multiple times)
        for attempt in range(3):
            # Try multiple methods to bring up the adapter
            self._run_command(["sudo", "hciconfig", "hci0", "up"])
            self._run_command(["sudo", "bluetoothctl", "power", "on"])
            time.sleep(0.5)
            
            # Verify it's actually up
            _, status = self._run_command(["hciconfig", "hci0"])
            if "UP RUNNING" in status:
                log.info("Bluetooth adapter is up and running")
                break
            log.warning(f"Attempt {attempt + 1} to bring up hci0 failed, retrying...")
            time.sleep(1)
        else:
            log.error("Failed to bring up Bluetooth adapter after 3 attempts")
        
        # Set device class to "Computer - Uncategorized" with NO service classes
        # This prevents Android from thinking it's an audio device
        # Class 0x000100 = Major: Computer (0x01), Minor: Uncategorized (0x00), No services
        self._run_command(["sudo", "hciconfig", "hci0", "class", "0x000100"])
        
        # Disable audio profiles (A2DP, HFP, HSP) by unloading PulseAudio Bluetooth modules
        # and ensuring BlueZ doesn't advertise audio capabilities
        self._run_command(["sudo", "killall", "pulseaudio"])  # Stop PulseAudio if running
        
        # Set device name using multiple methods for compatibility
        self._run_command(["bluetoothctl", "system-alias", self.config.device_name])
        self._run_command(["sudo", "hciconfig", "hci0", "name", self.config.device_name])
        
        # Make discoverable using hciconfig (more reliable than bluetoothctl)
        success, output = self._run_command(["sudo", "hciconfig", "hci0", "piscan"])
        if not success:
            log.warning(f"hciconfig piscan failed: {output}")
        else:
            log.info("Enabled page and inquiry scan (piscan)")
        
        # Start the D-Bus Bluetooth agent for automatic PIN-less pairing
        try:
            start_agent()
            log.info("Started Bluetooth auto-pair agent (no PIN required)")
        except Exception as e:
            log.warning(f"Could not start Bluetooth agent: {e}")
            # Fall back to bluetoothctl commands
            self._run_command(["bluetoothctl", "agent", "NoInputNoOutput"])
            self._run_command(["bluetoothctl", "default-agent"])
        
        # Also try bluetoothctl for compatibility
        self._run_command(["bluetoothctl", "discoverable", "on"])
        self._run_command(["bluetoothctl", "pairable", "on"])
        
        # Verify discoverability
        success, output = self._run_command(["hciconfig", "hci0"])
        if "PSCAN" in output and "ISCAN" in output:
            log.info(f"Bluetooth configured as '{self.config.device_name}' - discoverable and connectable")
        else:
            log.warning(f"Bluetooth may not be fully discoverable. hciconfig output: {output}")
        
        return True
    
    def _cleanup_bluetooth(self) -> None:
        """Disable discoverable/pairable mode and stop agent."""
        stop_agent()
        self._run_command(["bluetoothctl", "discoverable", "off"])
        self._run_command(["bluetoothctl", "pairable", "off"])
    
    def _send_led_status(self, colors: list) -> None:
        """Send LED status colors."""
        if self.led_controller and self.led_controller.is_connected():
            color_string = ",".join(colors)
            command = f"C:{color_string}"
            self.led_controller._send_command(command)
    
    def _get_current_config(self) -> dict:
        """Get the current configuration from config store."""
        from .config_store import ConfigStore
        config_store = ConfigStore()
        user_config = config_store.load()
        return {
            "team_abbr": user_config.team_abbr,
            "celebration_delay_seconds": user_config.celebration_delay_seconds,
            "ip_address": self._get_ip_address()
        }
    
    def _get_ip_address(self) -> Optional[str]:
        """Get the current IP address of wlan0."""
        try:
            result = subprocess.run(
                ["ip", "-4", "addr", "show", "wlan0"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'inet ' in line:
                        parts = line.strip().split()
                        addr = parts[1].split('/')[0]
                        return addr
        except Exception:
            pass
        return None
    
    def _get_local_bluetooth_address(self) -> Optional[str]:
        """Get the local Bluetooth adapter MAC address."""
        try:
            result = subprocess.run(
                ["hciconfig", "hci0"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                # Parse output for BD Address
                for line in result.stdout.split('\n'):
                    if 'BD Address:' in line:
                        # Format: "BD Address: XX:XX:XX:XX:XX:XX"
                        parts = line.split('BD Address:')
                        if len(parts) > 1:
                            addr = parts[1].strip().split()[0]
                            return addr
            
            # Fallback: try bluetoothctl
            result = subprocess.run(
                ["bluetoothctl", "show"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'Controller' in line:
                        # Format: "Controller XX:XX:XX:XX:XX:XX ..."
                        parts = line.split()
                        if len(parts) >= 2:
                            return parts[1]
            
            return None
        except Exception as e:
            log.error(f"Error getting Bluetooth address: {e}")
            return None
    
    def _register_sdp_service(self) -> bool:
        """Register SPP service with SDP using sdptool."""
        try:
            # Add SPP service record (requires sudo)
            result = subprocess.run(
                ["sudo", "sdptool", "add", "--channel", str(self.config.channel), "SP"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                log.info(f"Registered SPP service on channel {self.config.channel}")
                return True
            else:
                log.warning(f"sdptool add failed: {result.stderr}")
                return False
        except FileNotFoundError:
            log.warning("sdptool not found, skipping SDP registration")
            return True  # Continue anyway
        except Exception as e:
            log.warning(f"SDP registration error: {e}")
            return True  # Continue anyway
    
    def start(self) -> Optional[ReceivedConfig]:
        """Start Bluetooth server and wait for configuration.
        
        Returns:
            ReceivedConfig if configuration received, None on timeout/error.
        """
        log.info("Starting Bluetooth configuration server")
        self._running = True
        
        # Connect to LED controller if available
        if self.led_controller:
            self.led_controller.connect()
        
        try:
            # Setup Bluetooth
            if not self._setup_bluetooth():
                self._send_led_status(["FF0000"])  # Red for error
                return None
            
            # Register SDP service
            self._register_sdp_service()
            
            # Show blue LED - waiting for connection
            self._send_led_status(["0000FF"])
            
            # Create RFCOMM server socket
            self._server_socket = socket.socket(
                socket.AF_BLUETOOTH,
                socket.SOCK_STREAM,
                socket.BTPROTO_RFCOMM
            )
            self._server_socket.settimeout(self.config.timeout)
            
            # Get local Bluetooth adapter address
            local_addr = self._get_local_bluetooth_address()
            if not local_addr:
                log.error("Could not find local Bluetooth adapter address")
                self._send_led_status(["FF0000"])  # Red for error
                return None
            
            log.info(f"Binding to Bluetooth address: {local_addr}")
            self._server_socket.bind((local_addr, self.config.channel))
            self._server_socket.listen(1)
            
            log.info(f"Listening for Bluetooth connections on channel {self.config.channel}")
            
            # Wait for connection
            try:
                self._client_socket, client_info = self._server_socket.accept()
                log.info(f"Connected to {client_info}")
                
                # Show cyan LED - connected, waiting for data
                self._send_led_status(["00FFFF"])
                
                # Receive and process messages
                self._client_socket.settimeout(300)  # 5 minute timeout for data
                data = b""
                while self._running:
                    try:
                        chunk = self._client_socket.recv(1024)
                        if not chunk:
                            break
                        data += chunk
                        
                        # Try to parse JSON
                        try:
                            message_json = json.loads(data.decode('utf-8'))
                            data = b""  # Reset buffer after successful parse
                            
                            msg_type = message_json.get("type")
                            
                            if msg_type == "get_config":
                                # Return current configuration
                                current_config = self._get_current_config()
                                response = json.dumps({
                                    "status": "ok",
                                    "config": current_config
                                })
                                self._client_socket.send(response.encode('utf-8'))
                                continue  # Keep listening for more commands
                            
                            elif msg_type == "test_goal":
                                # Handle test goal - trigger celebration and continue
                                self._trigger_test_goal()
                                response = json.dumps({"status": "ok"})
                                self._client_socket.send(response.encode('utf-8'))
                                continue  # Keep listening for more commands
                            
                            elif msg_type == "config":
                                # Handle config - process and return
                                received_config = self._process_config(message_json)
                                if received_config:
                                    response = json.dumps({"status": "ok"})
                                    self._client_socket.send(response.encode('utf-8'))
                                    
                                    # Show green LED - success
                                    self._send_led_status(["00FF00"])
                                    
                                    if self._on_config_received:
                                        self._on_config_received(received_config)
                                    
                                    return received_config
                            else:
                                log.warning(f"Unknown message type: {msg_type}")
                                response = json.dumps({"status": "error", "message": "unknown type"})
                                self._client_socket.send(response.encode('utf-8'))
                                
                        except json.JSONDecodeError:
                            # Not complete JSON yet, keep reading
                            continue
                    except socket.timeout:
                        log.warning("Timeout waiting for data")
                        break
                
            except socket.timeout:
                log.warning("Timeout waiting for Bluetooth connection")
                self._send_led_status(["FF0000"])  # Red for timeout
                return None
            
        except Exception as e:
            log.error(f"Bluetooth server error: {e}")
            self._send_led_status(["FF0000"])  # Red for error
            return None
        finally:
            self._cleanup()
    
    def _process_message(self, message_json: dict) -> bool:
        """Process received message. Returns True if should continue listening."""
        msg_type = message_json.get("type")
        
        if msg_type == "test_goal":
            log.info("Received test goal command")
            self._trigger_test_goal()
            return True  # Continue listening for more commands
        elif msg_type == "config":
            return False  # Config handled separately, stop listening
        else:
            log.warning(f"Unknown message type: {msg_type}")
            return True
    
    def _trigger_test_goal(self) -> None:
        """Trigger a test goal celebration."""
        if self.led_controller:
            log.info("Triggering test goal celebration!")
            # Get current team from config
            current_config = self._get_current_config()
            team_abbr = current_config.get("team_abbr", "WSH")
            self.led_controller.celebrate(team_abbr)
    
    def _process_config(self, config_json: dict) -> Optional[ReceivedConfig]:
        """Process received configuration JSON."""
        try:
            if config_json.get("type") != "config":
                log.warning(f"Unknown message type: {config_json.get('type')}")
                return None
            
            wifi_ssid = config_json.get("wifi_ssid", "")
            wifi_password = config_json.get("wifi_password", "")
            team_abbr = config_json.get("team_abbr", "WSH")
            celebration_delay = config_json.get("celebration_delay_seconds", 0)
            
            log.info(f"Received config - SSID: {wifi_ssid}, Team: {team_abbr}, Delay: {celebration_delay}s")
            
            # Configure WiFi if credentials provided
            if wifi_ssid and wifi_password:
                from .wifi_config import configure_wifi
                if configure_wifi(wifi_ssid, wifi_password):
                    log.info(f"WiFi configured for network: {wifi_ssid}")
                else:
                    log.warning(f"Failed to configure WiFi for network: {wifi_ssid}")
            
            # Save team and delay configuration
            from .config_store import ConfigStore
            config_store = ConfigStore()
            config_store.set_team(team_abbr)
            config_store.set_celebration_delay(celebration_delay)
            
            return ReceivedConfig(
                wifi_ssid=wifi_ssid,
                wifi_password=wifi_password,
                team_abbr=team_abbr
            )
        except Exception as e:
            log.error(f"Error processing config: {e}")
            return None
    
    def _cleanup(self) -> None:
        """Clean up sockets and Bluetooth settings."""
        self._running = False
        
        if self._client_socket:
            try:
                self._client_socket.close()
            except:
                pass
            self._client_socket = None
        
        if self._server_socket:
            try:
                self._server_socket.close()
            except:
                pass
            self._server_socket = None
        
        self._cleanup_bluetooth()
        
        # Give time for LED animation
        time.sleep(2)
        
        if self.led_controller:
            self.led_controller.idle()
    
    def stop(self) -> None:
        """Stop the Bluetooth server."""
        log.info("Stopping Bluetooth server")
        self._running = False
        self._cleanup()
    
    def is_running(self) -> bool:
        """Check if the server is running."""
        return self._running


class BluetoothCommandServer:
    """
    Background Bluetooth server that accepts commands from the Android app.
    Runs continuously during normal operation to handle test_goal, get_config, etc.
    """
    
    def __init__(self, led_controller=None, config_store=None):
        self.led_controller = led_controller
        self.config_store = config_store
        self._running = False
        self._server_socket = None
        self._thread = None
    
    def _run_command(self, cmd: list) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            return False, str(e)
    
    def _get_local_bluetooth_address(self) -> Optional[str]:
        """Get the local Bluetooth adapter address."""
        success, output = self._run_command(["hciconfig", "hci0"])
        if success:
            for line in output.split('\n'):
                if 'BD Address:' in line:
                    parts = line.split('BD Address:')
                    if len(parts) > 1:
                        addr = parts[1].strip().split()[0]
                        return addr
        return None
    
    def _get_ip_address(self) -> Optional[str]:
        """Get the current IP address of wlan0."""
        try:
            result = subprocess.run(
                ["ip", "-4", "addr", "show", "wlan0"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'inet ' in line:
                        parts = line.strip().split()
                        addr = parts[1].split('/')[0]
                        return addr
        except Exception:
            pass
        return None
    
    def _get_current_config(self) -> dict:
        """Get current configuration."""
        if self.config_store:
            config = self.config_store.load()
            return {
                "team_abbr": config.team_abbr,
                "celebration_delay_seconds": config.celebration_delay_seconds,
                "ip_address": self._get_ip_address()
            }
        return {"team_abbr": "WSH", "celebration_delay_seconds": 0, "ip_address": None}
    
    def _trigger_test_goal(self) -> None:
        """Trigger a test goal celebration."""
        if self.led_controller:
            log.info("Triggering test goal celebration!")
            current_config = self._get_current_config()
            team_abbr = current_config.get("team_abbr", "WSH")
            self.led_controller.celebrate(team_abbr)
    
    def _handle_client(self, client_socket, client_info) -> None:
        """Handle a connected client."""
        log.info(f"Background BT server: client connected from {client_info}")
        client_socket.settimeout(60)  # 1 minute timeout
        
        try:
            data = b""
            while self._running:
                try:
                    chunk = client_socket.recv(1024)
                    if not chunk:
                        break
                    data += chunk
                    
                    # Try to parse JSON
                    try:
                        message_json = json.loads(data.decode('utf-8'))
                        data = b""  # Reset buffer
                        
                        msg_type = message_json.get("type")
                        log.debug(f"Background BT server received: {msg_type}")
                        
                        if msg_type == "get_config":
                            current_config = self._get_current_config()
                            response = json.dumps({
                                "status": "ok",
                                "config": current_config
                            })
                            client_socket.send(response.encode('utf-8'))
                        
                        elif msg_type == "test_goal":
                            self._trigger_test_goal()
                            response = json.dumps({"status": "ok"})
                            client_socket.send(response.encode('utf-8'))
                        
                        elif msg_type == "config":
                            # Handle config update
                            team_abbr = message_json.get("team_abbr", "WSH")
                            celebration_delay = message_json.get("celebration_delay_seconds", 0)
                            if self.config_store:
                                self.config_store.set_team(team_abbr)
                                self.config_store.set_celebration_delay(celebration_delay)
                            response = json.dumps({"status": "ok"})
                            client_socket.send(response.encode('utf-8'))
                        
                        else:
                            response = json.dumps({"status": "error", "message": "unknown type"})
                            client_socket.send(response.encode('utf-8'))
                            
                    except json.JSONDecodeError:
                        continue  # Keep reading
                        
                except socket.timeout:
                    break
                    
        except Exception as e:
            log.error(f"Background BT server client error: {e}")
        finally:
            try:
                client_socket.close()
            except:
                pass
            log.info("Background BT server: client disconnected")
    
    def _register_sdp_service(self) -> None:
        """Register SDP service for SPP."""
        # Add SP profile so Android can find us via SPP UUID
        self._run_command(["sudo", "sdptool", "add", "SP"])
        log.info("Registered SPP service with SDP")
    
    def _server_loop(self) -> None:
        """Main server loop - accepts connections and handles them."""
        log.info("Background Bluetooth command server starting...")
        
        # Unblock Bluetooth via rfkill (required on Pi Zero W 2)
        self._run_command(["sudo", "rfkill", "unblock", "bluetooth"])
        time.sleep(0.5)
        
        # Ensure Bluetooth is up and connectable
        self._run_command(["sudo", "hciconfig", "hci0", "up"])
        self._run_command(["sudo", "bluetoothctl", "power", "on"])
        time.sleep(0.5)
        
        # Make connectable (piscan) so paired devices can connect
        self._run_command(["sudo", "hciconfig", "hci0", "piscan"])
        
        # Register SDP service so Android can find us
        self._register_sdp_service()
        
        try:
            self._server_socket = socket.socket(
                socket.AF_BLUETOOTH,
                socket.SOCK_STREAM,
                socket.BTPROTO_RFCOMM
            )
            self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_socket.settimeout(5)  # Short timeout for accept to allow clean shutdown
            
            local_addr = self._get_local_bluetooth_address()
            if not local_addr:
                log.error("Background BT server: Could not find Bluetooth adapter")
                return
            
            # Use channel 1 (standard SPP channel) for compatibility with Android
            channel = 1
            self._server_socket.bind((local_addr, channel))
            self._server_socket.listen(1)
            
            log.info(f"Background Bluetooth command server listening on channel {channel}")
            
            while self._running:
                try:
                    client_socket, client_info = self._server_socket.accept()
                    # Handle client in same thread (one at a time)
                    self._handle_client(client_socket, client_info)
                except socket.timeout:
                    continue  # Just loop and check if still running
                except Exception as e:
                    if self._running:
                        log.error(f"Background BT server accept error: {e}")
                    break
                    
        except Exception as e:
            log.error(f"Background BT server error: {e}")
        finally:
            if self._server_socket:
                try:
                    self._server_socket.close()
                except:
                    pass
            log.info("Background Bluetooth command server stopped")
    
    def start(self) -> bool:
        """Start the background Bluetooth command server."""
        if self._running:
            return True
        
        self._running = True
        self._thread = threading.Thread(
            target=self._server_loop,
            daemon=True,
            name="BluetoothCommandServer"
        )
        self._thread.start()
        return True
    
    def stop(self) -> None:
        """Stop the background Bluetooth command server."""
        log.info("Stopping background Bluetooth command server...")
        self._running = False
        if self._server_socket:
            try:
                self._server_socket.close()
            except:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
    
    def is_running(self) -> bool:
        """Check if the server is running."""
        return self._running
