import logging
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    log.warning("RPi.GPIO not available - ESP32 reset functionality disabled")


@dataclass
class ResetConfig:
    reset_pin: int = 27  # BCM GPIO pin connected to ESP32 EN pin
    reset_pulse_duration: float = 0.1  # 100ms low pulse
    post_reset_delay: float = 2.0  # Wait for ESP32 to boot


class ESP32Reset:
    def __init__(self, config: ResetConfig = None):
        self.config = config or ResetConfig()
        self._initialized = False
    
    def _setup_gpio(self) -> bool:
        if not GPIO_AVAILABLE:
            log.error("GPIO not available on this platform")
            return False
        
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            # Set pin HIGH initially (ESP32 runs when EN is HIGH)
            GPIO.setup(self.config.reset_pin, GPIO.OUT, initial=GPIO.HIGH)
            self._initialized = True
            log.info(f"ESP32 reset pin configured on GPIO {self.config.reset_pin}")
            return True
        except Exception as e:
            log.error(f"Failed to setup reset GPIO: {e}")
            return False
    
    def reset(self) -> bool:
        if not self._initialized:
            if not self._setup_gpio():
                return False
        
        try:
            log.info("Resetting ESP32...")
            
            # Pull EN low to reset
            GPIO.output(self.config.reset_pin, GPIO.LOW)
            time.sleep(self.config.reset_pulse_duration)
            
            # Release EN (back to HIGH) to allow boot
            GPIO.output(self.config.reset_pin, GPIO.HIGH)
            
            # Wait for ESP32 to boot
            log.info(f"Waiting {self.config.post_reset_delay}s for ESP32 to boot...")
            time.sleep(self.config.post_reset_delay)
            
            log.info("ESP32 reset complete")
            return True
            
        except Exception as e:
            log.error(f"Failed to reset ESP32: {e}")
            return False
    
    def cleanup(self) -> None:
        if self._initialized and GPIO_AVAILABLE:
            try:
                GPIO.cleanup(self.config.reset_pin)
            except Exception:
                pass
            self._initialized = False
