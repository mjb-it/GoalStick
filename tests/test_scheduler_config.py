import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Mock nhlpy before any StickCheck imports
sys.modules['nhlpy'] = MagicMock()

from StickCheck.scheduler import SchedulerConfig


class TestSchedulerConfig:
    def test_default_values(self):
        config = SchedulerConfig()
        
        assert config.team_abbr is None
        assert config.check_interval == 0.5
        assert config.daily_check_hour == 8
        assert config.pre_game_wake_minutes == 5
        assert config.api_timeout == 10
        assert config.max_retries == 3
        assert config.serial_port == "/dev/serial0"
        assert config.serial_baud_rate == 115200
        assert config.team_colors_path is None
        assert config.bluetooth_device_name == "GoalStick"
        assert config.bluetooth_pairing_timeout == 180
        assert config.pairing_button_pin == 17
        assert config.pairing_button_hold_time == 3.0
        assert config.esp32_reset_pin == 27
        assert config.esp32_reset_retries == 2
    
    def test_custom_values(self):
        config = SchedulerConfig(
            team_abbr="TOR",
            check_interval=1.0,
            daily_check_hour=9,
            pre_game_wake_minutes=10,
            esp32_reset_pin=22,
            esp32_reset_retries=3
        )
        
        assert config.team_abbr == "TOR"
        assert config.check_interval == 1.0
        assert config.daily_check_hour == 9
        assert config.pre_game_wake_minutes == 10
        assert config.esp32_reset_pin == 22
        assert config.esp32_reset_retries == 3
