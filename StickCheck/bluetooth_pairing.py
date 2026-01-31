import logging
import subprocess
import threading
import time
from typing import Optional, Callable
from dataclasses import dataclass
from enum import Enum

log = logging.getLogger(__name__)


class PairingStatus(Enum):
    WAITING = "waiting"
    SUCCESS = "success"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass
class BluetoothConfig:
    device_name: str = "GoalStick"
    pairing_timeout: int = 180  # 3 minutes in seconds
    discoverable_timeout: int = 180


# Status LED colors
LED_PAIRING_WAITING = ["0000FF"]  # Blue - waiting for connection
LED_PAIRING_SUCCESS = ["FFFFFF"]  # White - successful pairing
LED_PAIRING_TIMEOUT = ["FF0000"]  # Red - timeout/failure


class BluetoothPairing:
    def __init__(self, config: BluetoothConfig = None, led_controller=None):
        self.config = config or BluetoothConfig()
        self.led_controller = led_controller
        self._pairing_active = False
        self._connected_device: Optional[str] = None
        self._on_team_received: Optional[Callable[[str], None]] = None
    
    def set_team_callback(self, callback: Callable[[str], None]) -> None:
        self._on_team_received = callback
    
    def _send_led_status(self, colors: list) -> None:
        if self.led_controller and self.led_controller.is_connected():
            color_string = ",".join(colors)
            command = f"C:{color_string}"
            self.led_controller._send_command(command)
    
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
    
    def _set_discoverable(self, enabled: bool) -> bool:
        mode = "on" if enabled else "off"
        success, output = self._run_command(["bluetoothctl", "discoverable", mode])
        if success:
            log.info(f"Bluetooth discoverable: {mode}")
        else:
            log.error(f"Failed to set discoverable {mode}: {output}")
        return success
    
    def _set_pairable(self, enabled: bool) -> bool:
        mode = "on" if enabled else "off"
        success, output = self._run_command(["bluetoothctl", "pairable", mode])
        if success:
            log.info(f"Bluetooth pairable: {mode}")
        else:
            log.error(f"Failed to set pairable {mode}: {output}")
        return success
    
    def _set_agent(self) -> bool:
        success, output = self._run_command(["bluetoothctl", "agent", "NoInputNoOutput"])
        if not success:
            log.error(f"Failed to set agent: {output}")
            return False
        
        success, output = self._run_command(["bluetoothctl", "default-agent"])
        if not success:
            log.error(f"Failed to set default agent: {output}")
            return False
        
        log.info("Bluetooth agent configured")
        return True
    
    def _set_device_name(self) -> bool:
        success, output = self._run_command(
            ["bluetoothctl", "system-alias", self.config.device_name]
        )
        if success:
            log.info(f"Bluetooth device name set to: {self.config.device_name}")
        else:
            log.warning(f"Could not set device name: {output}")
        return success
    
    def _monitor_connections(self, timeout: int) -> PairingStatus:
        start_time = time.time()
        check_interval = 1.0  # Check every second
        
        while self._pairing_active and (time.time() - start_time) < timeout:
            # Check for connected devices
            success, output = self._run_command(["bluetoothctl", "devices", "Connected"])
            
            if success and output.strip():
                # Parse connected device
                lines = output.strip().split('\n')
                for line in lines:
                    if line.startswith("Device"):
                        parts = line.split(' ', 2)
                        if len(parts) >= 2:
                            self._connected_device = parts[1]
                            log.info(f"Device connected: {self._connected_device}")
                            return PairingStatus.SUCCESS
            
            time.sleep(check_interval)
        
        return PairingStatus.TIMEOUT
    
    def start_pairing_mode(self) -> PairingStatus:
        log.info("Starting Bluetooth pairing mode")
        self._pairing_active = True
        self._connected_device = None
        
        # Connect to LED controller if available
        if self.led_controller:
            self.led_controller.connect()
        
        try:
            # Set up Bluetooth for pairing
            self._set_device_name()
            self._set_agent()
            self._set_pairable(True)
            self._set_discoverable(True)
            
            # Send blue LED to indicate waiting
            log.info("Waiting for Bluetooth connection...")
            self._send_led_status(LED_PAIRING_WAITING)
            
            # Monitor for connections
            status = self._monitor_connections(self.config.pairing_timeout)
            
            # Send appropriate LED feedback
            if status == PairingStatus.SUCCESS:
                log.info("Bluetooth pairing successful!")
                self._send_led_status(LED_PAIRING_SUCCESS)
            elif status == PairingStatus.TIMEOUT:
                log.warning("Bluetooth pairing timed out")
                self._send_led_status(LED_PAIRING_TIMEOUT)
            
            return status
            
        except Exception as e:
            log.error(f"Bluetooth pairing error: {e}")
            self._send_led_status(LED_PAIRING_TIMEOUT)
            return PairingStatus.ERROR
        finally:
            # Clean up
            self._pairing_active = False
            self._set_discoverable(False)
            self._set_pairable(False)
            
            # Give time for LED animation to play
            time.sleep(2)
            
            if self.led_controller:
                self.led_controller.idle()
    
    def stop_pairing_mode(self) -> None:
        log.info("Stopping Bluetooth pairing mode")
        self._pairing_active = False
    
    def is_pairing_active(self) -> bool:
        return self._pairing_active
    
    def get_connected_device(self) -> Optional[str]:
        return self._connected_device
