import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

log = logging.getLogger(__name__)

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    log.warning("RPi.GPIO not available - status LED disabled")


class DeviceState(Enum):
    """Device states with corresponding LED colors."""
    OFF = "off"                   # LED off - normal operation
    BOOTING = "booting"           # Yellow - starting up
    PAIRING = "pairing"           # Blue blink - Bluetooth pairing mode
    ERROR = "error"               # Red solid - error state
    NO_NETWORK = "no_network"     # Red blink - no network connectivity
    UPDATING = "updating"         # Cyan blink - updating


@dataclass
class StatusLEDConfig:
    red_pin: int = 22      # BCM GPIO pin for red
    green_pin: int = 23    # BCM GPIO pin for green
    blue_pin: int = 24     # BCM GPIO pin for blue
    common_anode: bool = False  # True if common anode RGB LED


class StatusLED:
    """
    Controls an RGB status LED to indicate device state.
    
    Wiring (common cathode, active high):
    - Red:   GPIO 22 -> resistor -> LED red pin
    - Green: GPIO 23 -> resistor -> LED green pin
    - Blue:  GPIO 24 -> resistor -> LED blue pin
    - GND:   LED common cathode
    """
    
    # Color definitions (R, G, B) - 1 = on, 0 = off
    COLORS = {
        "off":     (0, 0, 0),
        "red":     (1, 0, 0),
        "green":   (0, 1, 0),
        "blue":    (0, 0, 1),
        "yellow":  (1, 1, 0),
        "cyan":    (0, 1, 1),
        "magenta": (1, 0, 1),
        "white":   (1, 1, 1),
    }
    
    # State to pattern mapping - only special states have LED on
    STATE_PATTERNS = {
        DeviceState.OFF:              ("off", "solid"),
        DeviceState.BOOTING:          ("yellow", "solid"),
        DeviceState.PAIRING:          ("blue", "slow_blink"),
        DeviceState.ERROR:            ("red", "solid"),
        DeviceState.NO_NETWORK:       ("red", "fast_blink"),
        DeviceState.UPDATING:         ("cyan", "slow_blink"),
    }
    
    def __init__(self, config: StatusLEDConfig = None):
        self.config = config or StatusLEDConfig()
        self._current_state: Optional[DeviceState] = None
        self._running = False
        self._blink_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
    
    def _setup_gpio(self) -> bool:
        """Initialize GPIO pins."""
        if not GPIO_AVAILABLE:
            return False
        
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            
            GPIO.setup(self.config.red_pin, GPIO.OUT)
            GPIO.setup(self.config.green_pin, GPIO.OUT)
            GPIO.setup(self.config.blue_pin, GPIO.OUT)
            
            # Start with LED off
            self._set_color("off")
            
            log.info(f"Status LED initialized on GPIO {self.config.red_pin}/{self.config.green_pin}/{self.config.blue_pin}")
            return True
            
        except Exception as e:
            log.error(f"Failed to setup status LED GPIO: {e}")
            return False
    
    def _cleanup_gpio(self) -> None:
        """Clean up GPIO pins."""
        if GPIO_AVAILABLE:
            try:
                self._set_color("off")
                GPIO.cleanup([self.config.red_pin, self.config.green_pin, self.config.blue_pin])
            except Exception:
                pass
    
    def _set_color(self, color: str) -> None:
        """Set the LED to a specific color."""
        if not GPIO_AVAILABLE:
            return
        
        r, g, b = self.COLORS.get(color, (0, 0, 0))
        
        # Invert for common anode
        if self.config.common_anode:
            r, g, b = 1 - r, 1 - g, 1 - b
        
        GPIO.output(self.config.red_pin, r)
        GPIO.output(self.config.green_pin, g)
        GPIO.output(self.config.blue_pin, b)
    
    def _blink_loop(self) -> None:
        """Background thread for blinking patterns."""
        while self._running:
            with self._lock:
                state = self._current_state
            
            if state is None:
                time.sleep(0.1)
                continue
            
            color, pattern = self.STATE_PATTERNS.get(state, ("off", "solid"))
            
            if pattern == "solid":
                self._set_color(color)
                time.sleep(0.5)
            elif pattern == "slow_blink":
                self._set_color(color)
                time.sleep(1.0)
                self._set_color("off")
                time.sleep(1.0)
            elif pattern == "fast_blink":
                self._set_color(color)
                time.sleep(0.2)
                self._set_color("off")
                time.sleep(0.2)
    
    def start(self) -> bool:
        """Start the status LED controller."""
        if self._running:
            return True
        
        if not self._setup_gpio():
            log.warning("Status LED not available")
            return False
        
        self._running = True
        self._blink_thread = threading.Thread(
            target=self._blink_loop,
            daemon=True,
            name="StatusLED"
        )
        self._blink_thread.start()
        
        # Start in booting state
        self.set_state(DeviceState.BOOTING)
        return True
    
    def stop(self) -> None:
        """Stop the status LED controller."""
        self._running = False
        if self._blink_thread and self._blink_thread.is_alive():
            self._blink_thread.join(timeout=1.0)
        self._cleanup_gpio()
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
