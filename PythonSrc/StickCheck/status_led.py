import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

log = logging.getLogger(__name__)


class DeviceState(Enum):
    """Device states with corresponding LED strip colors."""
    OFF = "off"                   # LED off - normal operation
    BOOTING = "booting"           # Yellow - starting up
    PAIRING = "pairing"           # Blue blink - Bluetooth pairing mode
    ERROR = "error"               # Red solid - error state
    NO_NETWORK = "no_network"     # Red blink - no network connectivity
    NO_WIFI_CONFIG = "no_wifi"    # Magenta blink - WiFi not configured
    UPDATING = "updating"         # Cyan blink - updating


@dataclass 
class StatusLEDConfig:
    """Configuration for status LED (kept for compatibility, not used)."""
    pass


class StatusLED:
    """
    Controls the LED strip to indicate device state.
    Uses the existing LED controller to send colors to the ESP32/LED strip.
    """
    
    # Color definitions as hex strings for LED strip
    # Format: RRGGBB
    COLORS = {
        "off":     "000000",
        "red":     "FF0000",
        "green":   "00FF00",
        "blue":    "0000FF",
        "yellow":  "FFFF00",
        "cyan":    "00FFFF",
        "magenta": "FF00FF",
        "white":   "FFFFFF",
    }
    
    # State to pattern mapping - only special states have LED on
    STATE_PATTERNS = {
        DeviceState.OFF:              ("off", "solid"),
        DeviceState.BOOTING:          ("yellow", "solid"),
        DeviceState.PAIRING:          ("blue", "slow_blink"),
        DeviceState.ERROR:            ("red", "solid"),
        DeviceState.NO_NETWORK:       ("red", "fast_blink"),
        DeviceState.NO_WIFI_CONFIG:   ("magenta", "slow_blink"),
        DeviceState.UPDATING:         ("cyan", "slow_blink"),
    }
    
    def __init__(self, config: StatusLEDConfig = None, led_controller=None):
        self.config = config or StatusLEDConfig()
        self._led_controller = led_controller
        self._current_state: Optional[DeviceState] = None
        self._running = False
        self._blink_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
    
    def set_led_controller(self, led_controller) -> None:
        """Set the LED controller for sending colors to the strip."""
        self._led_controller = led_controller
    
    def _send_color(self, color: str) -> None:
        """Send a color to the LED strip."""
        if not self._led_controller:
            return
        
        hex_color = self.COLORS.get(color, "000000")
        
        if hex_color == "000000":
            # Send idle command to turn off
            self._led_controller.idle()
        else:
            # Send celebration command with single color
            command = f"C:{hex_color}"
            self._led_controller._send_command(command)
    
    def _blink_loop(self) -> None:
        """Background thread for blinking patterns."""
        while self._running:
            with self._lock:
                state = self._current_state
            
            if state is None:
                time.sleep(0.1)
                continue
            
            color, pattern = self.STATE_PATTERNS.get(state, ("off", "solid"))
            
            # When OFF, don't send any commands - let other code control the LED strip
            if state == DeviceState.OFF:
                time.sleep(0.5)
                continue
            
            if pattern == "solid":
                self._send_color(color)
                time.sleep(0.5)
            elif pattern == "slow_blink":
                self._send_color(color)
                time.sleep(1.0)
                self._send_color("off")
                time.sleep(1.0)
            elif pattern == "fast_blink":
                self._send_color(color)
                time.sleep(0.2)
                self._send_color("off")
                time.sleep(0.2)
    
    def start(self) -> bool:
        """Start the status LED controller."""
        if self._running:
            return True
        
        self._running = True
        self._blink_thread = threading.Thread(
            target=self._blink_loop,
            daemon=True,
            name="StatusLED"
        )
        self._blink_thread.start()
        
        log.info("Status LED started (using LED strip)")
        
        # Start in booting state
        self.set_state(DeviceState.BOOTING)
        return True
    
    def stop(self) -> None:
        """Stop the status LED controller."""
        self._running = False
        if self._blink_thread and self._blink_thread.is_alive():
            self._blink_thread.join(timeout=1.0)
        # Turn off LED strip
        self._send_color("off")
        log.info("Status LED stopped")
    
    def set_state(self, state: DeviceState) -> None:
        """Set the current device state."""
        with self._lock:
            if self._current_state != state:
                self._current_state = state
                log.debug(f"Status LED: {state.value}")
    
    def get_state(self) -> Optional[DeviceState]:
        """Get the current device state."""
        with self._lock:
            return self._current_state
