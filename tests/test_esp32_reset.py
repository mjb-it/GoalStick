import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Mock nhlpy before any StickCheck imports
sys.modules['nhlpy'] = MagicMock()

from StickCheck.esp32_reset import ESP32Reset, ResetConfig


class TestResetConfig:
    def test_default_values(self):
        config = ResetConfig()
        assert config.reset_pin == 27
        assert config.reset_pulse_duration == 0.1
        assert config.post_reset_delay == 2.0
    
    def test_custom_values(self):
        config = ResetConfig(
            reset_pin=22,
            reset_pulse_duration=0.2,
            post_reset_delay=3.0
        )
        assert config.reset_pin == 22
        assert config.reset_pulse_duration == 0.2
        assert config.post_reset_delay == 3.0


class TestESP32Reset:
    def test_not_initialized_initially(self):
        reset = ESP32Reset()
        assert reset._initialized is False
    
    @patch('StickCheck.esp32_reset.GPIO_AVAILABLE', False)
    def test_setup_gpio_not_available(self):
        reset = ESP32Reset()
        result = reset._setup_gpio()
        assert result is False
    
    def test_setup_gpio_success(self):
        import StickCheck.esp32_reset as esp32_mod
        mock_gpio = MagicMock()
        esp32_mod.GPIO = mock_gpio
        esp32_mod.GPIO_AVAILABLE = True
        
        reset = ESP32Reset()
        result = reset._setup_gpio()
        
        assert result is True
        assert reset._initialized is True
        mock_gpio.setmode.assert_called_once()
        mock_gpio.setup.assert_called_once()
    
    def test_reset_success(self):
        import StickCheck.esp32_reset as esp32_mod
        mock_gpio = MagicMock()
        esp32_mod.GPIO = mock_gpio
        esp32_mod.GPIO_AVAILABLE = True
        
        config = ResetConfig(reset_pulse_duration=0.1, post_reset_delay=2.0)
        reset = ESP32Reset(config=config)
        
        with patch('StickCheck.esp32_reset.time.sleep'):
            result = reset.reset()
        
        assert result is True
        # Should pull LOW then HIGH
        assert mock_gpio.output.call_count == 2
    
    def test_reset_initializes_gpio_if_needed(self):
        import StickCheck.esp32_reset as esp32_mod
        mock_gpio = MagicMock()
        esp32_mod.GPIO = mock_gpio
        esp32_mod.GPIO_AVAILABLE = True
        
        reset = ESP32Reset()
        assert reset._initialized is False
        
        with patch('StickCheck.esp32_reset.time.sleep'):
            reset.reset()
        
        assert reset._initialized is True
    
    def test_reset_fails_without_gpio(self):
        import StickCheck.esp32_reset as esp32_mod
        esp32_mod.GPIO_AVAILABLE = False
        
        reset = ESP32Reset()
        result = reset.reset()
        
        assert result is False
    
    def test_cleanup(self):
        import StickCheck.esp32_reset as esp32_mod
        mock_gpio = MagicMock()
        esp32_mod.GPIO = mock_gpio
        esp32_mod.GPIO_AVAILABLE = True
        
        reset = ESP32Reset()
        reset._initialized = True
        
        reset.cleanup()
        
        mock_gpio.cleanup.assert_called_once_with(27)
        assert reset._initialized is False
    
    def test_cleanup_not_initialized(self):
        import StickCheck.esp32_reset as esp32_mod
        mock_gpio = MagicMock()
        esp32_mod.GPIO = mock_gpio
        esp32_mod.GPIO_AVAILABLE = True
        
        reset = ESP32Reset()
        reset._initialized = False
        
        reset.cleanup()
        
        mock_gpio.cleanup.assert_not_called()
