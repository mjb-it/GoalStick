import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Mock nhlpy before any StickCheck imports
sys.modules['nhlpy'] = MagicMock()

from StickCheck.button_handler import ButtonHandler, ButtonConfig, ButtonState


class TestButtonConfig:
    def test_default_values(self):
        config = ButtonConfig()
        assert config.gpio_pin == 17
        assert config.hold_time == 3.0
        assert config.debounce_time == 0.05
        assert config.pull_up is True
    
    def test_custom_values(self):
        config = ButtonConfig(
            gpio_pin=22,
            hold_time=5.0,
            debounce_time=0.1,
            pull_up=False
        )
        assert config.gpio_pin == 22
        assert config.hold_time == 5.0
        assert config.debounce_time == 0.1
        assert config.pull_up is False


class TestButtonState:
    def test_enum_values(self):
        assert ButtonState.RELEASED.value == "released"
        assert ButtonState.PRESSED.value == "pressed"
        assert ButtonState.HELD.value == "held"


class TestButtonHandler:
    def test_initial_state(self):
        handler = ButtonHandler()
        assert handler._running is False
        assert handler._button_state == ButtonState.RELEASED
        assert handler._press_start_time is None
    
    def test_set_on_hold_callback(self):
        handler = ButtonHandler()
        callback = MagicMock()
        
        handler.set_on_hold(callback)
        
        assert handler._on_hold_callback == callback
    
    def test_set_on_press_callback(self):
        handler = ButtonHandler()
        callback = MagicMock()
        
        handler.set_on_press(callback)
        
        assert handler._on_press_callback == callback
    
    @patch('StickCheck.button_handler.GPIO_AVAILABLE', False)
    def test_setup_gpio_not_available(self):
        handler = ButtonHandler()
        result = handler._setup_gpio()
        assert result is False
    
    def test_setup_gpio_success(self):
        import StickCheck.button_handler as btn_mod
        mock_gpio = MagicMock()
        btn_mod.GPIO = mock_gpio
        btn_mod.GPIO_AVAILABLE = True
        
        handler = ButtonHandler()
        result = handler._setup_gpio()
        
        assert result is True
        mock_gpio.setmode.assert_called_once()
        mock_gpio.setup.assert_called_once()
    
    def test_start_fails_without_gpio(self):
        import StickCheck.button_handler as btn_mod
        btn_mod.GPIO_AVAILABLE = False
        
        handler = ButtonHandler()
        result = handler.start()
        
        assert result is False
        assert handler._running is False
    
    def test_stop(self):
        handler = ButtonHandler()
        handler._running = True
        
        handler.stop()
        
        assert handler._running is False
    
    def test_is_running(self):
        handler = ButtonHandler()
        assert handler.is_running() is False
        
        handler._running = True
        assert handler.is_running() is True
    
    def test_is_button_pressed_with_pull_up(self):
        import StickCheck.button_handler as btn_mod
        mock_gpio = MagicMock()
        mock_gpio.LOW = 0
        mock_gpio.HIGH = 1
        mock_gpio.input.return_value = 0  # LOW = pressed with pull-up
        btn_mod.GPIO = mock_gpio
        btn_mod.GPIO_AVAILABLE = True
        
        config = ButtonConfig(pull_up=True)
        handler = ButtonHandler(config=config)
        
        assert handler._is_button_pressed() is True
    
    def test_is_button_not_pressed_with_pull_up(self):
        import StickCheck.button_handler as btn_mod
        mock_gpio = MagicMock()
        mock_gpio.LOW = 0
        mock_gpio.HIGH = 1
        mock_gpio.input.return_value = 1  # HIGH = not pressed with pull-up
        btn_mod.GPIO = mock_gpio
        btn_mod.GPIO_AVAILABLE = True
        
        config = ButtonConfig(pull_up=True)
        handler = ButtonHandler(config=config)
        
        assert handler._is_button_pressed() is False
