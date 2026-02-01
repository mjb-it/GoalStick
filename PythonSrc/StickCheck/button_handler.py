import logging
import threading
import time
from typing import Callable, Optional
from dataclasses import dataclass
from enum import Enum

log = logging.getLogger(__name__)

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    log.warning("RPi.GPIO not available - button functionality disabled")


class ButtonState(Enum):
    RELEASED = "released"
    PRESSED = "pressed"
    HELD = "held"


@dataclass
class ButtonConfig:
    gpio_pin: int = 17  # BCM pin number
    hold_time: float = 3.0  # Seconds to hold for pairing trigger
    debounce_time: float = 0.05  # 50ms debounce
    pull_up: bool = True  # Use internal pull-up resistor


class ButtonHandler:
    def __init__(self, config: ButtonConfig = None):
        self.config = config or ButtonConfig()
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._on_hold_callback: Optional[Callable[[], None]] = None
        self._on_press_callback: Optional[Callable[[], None]] = None
        self._button_state = ButtonState.RELEASED
        self._press_start_time: Optional[float] = None
    
    def set_on_hold(self, callback: Callable[[], None]) -> None:
        self._on_hold_callback = callback
    
    def set_on_press(self, callback: Callable[[], None]) -> None:
        self._on_press_callback = callback
    
    def _setup_gpio(self) -> bool:
        if not GPIO_AVAILABLE:
            log.error("GPIO not available on this platform")
            return False
        
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            
            pull = GPIO.PUD_UP if self.config.pull_up else GPIO.PUD_DOWN
            GPIO.setup(self.config.gpio_pin, GPIO.IN, pull_up_down=pull)
            
            log.info(f"GPIO pin {self.config.gpio_pin} configured for button input")
            return True
        except Exception as e:
            log.error(f"Failed to setup GPIO: {e}")
            return False
    
    def _cleanup_gpio(self) -> None:
        if GPIO_AVAILABLE:
            try:
                GPIO.cleanup(self.config.gpio_pin)
            except Exception:
                pass
    
    def _is_button_pressed(self) -> bool:
        if not GPIO_AVAILABLE:
            return False
        
        # With pull-up, pressed = LOW (0)
        if self.config.pull_up:
            return GPIO.input(self.config.gpio_pin) == GPIO.LOW
        else:
            return GPIO.input(self.config.gpio_pin) == GPIO.HIGH
    
    def _monitor_loop(self) -> None:
        log.info("Button monitor started")
        hold_triggered = False
        
        while self._running:
            is_pressed = self._is_button_pressed()
            
            if is_pressed:
                if self._button_state == ButtonState.RELEASED:
                    # Button just pressed
                    self._button_state = ButtonState.PRESSED
                    self._press_start_time = time.time()
                    hold_triggered = False
                    log.debug("Button pressed")
                    
                    if self._on_press_callback:
                        self._on_press_callback()
                
                elif self._button_state == ButtonState.PRESSED:
                    # Check if held long enough
                    elapsed = time.time() - self._press_start_time
                    if elapsed >= self.config.hold_time and not hold_triggered:
                        self._button_state = ButtonState.HELD
                        hold_triggered = True
                        log.info(f"Button held for {self.config.hold_time}s - triggering action")
                        
                        if self._on_hold_callback:
                            # Run callback in separate thread to not block monitoring
                            threading.Thread(
                                target=self._on_hold_callback,
                                daemon=True
                            ).start()
            else:
                if self._button_state != ButtonState.RELEASED:
                    log.debug("Button released")
                    self._button_state = ButtonState.RELEASED
                    self._press_start_time = None
            
            time.sleep(self.config.debounce_time)
        
        log.info("Button monitor stopped")
    
    def start(self) -> bool:
        if self._running:
            log.warning("Button handler already running")
            return True
        
        if not self._setup_gpio():
            return False
        
        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="ButtonMonitor"
        )
        self._monitor_thread.start()
        return True
    
    def stop(self) -> None:
        log.info("Stopping button handler...")
        self._running = False
        
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=1.0)
        
        self._cleanup_gpio()
    
    def is_running(self) -> bool:
        return self._running
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False
