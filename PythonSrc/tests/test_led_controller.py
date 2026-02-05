import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Mock nhlpy before any StickCheck imports
sys.modules['nhlpy'] = MagicMock()

from StickCheck.led_controller import LEDController, LEDConfig


class TestLEDConfig:
    def test_default_values(self):
        config = LEDConfig()
        assert config.serial_port == "/dev/serial0"
        assert config.baud_rate == 115200
        assert config.timeout == 1.0
    
    def test_custom_values(self):
        config = LEDConfig(
            serial_port="/dev/ttyUSB0",
            baud_rate=9600,
            timeout=2.0
        )
        assert config.serial_port == "/dev/ttyUSB0"
        assert config.baud_rate == 9600
        assert config.timeout == 2.0


class TestLEDController:
    def test_load_team_colors(self, sample_team_colors):
        controller = LEDController(team_colors_path=str(sample_team_colors))
        
        assert controller.get_team_colors("WSH") == ["FFFFFF", "002D62", "FF0000"]
        assert controller.get_team_colors("TOR") == ["FFFFFF", "003876"]
        assert controller.get_team_colors("BOS") == ["FFFFFF", "FFC422", "231F20"]
    
    def test_get_team_colors_uppercase(self, sample_team_colors):
        controller = LEDController(team_colors_path=str(sample_team_colors))
        
        assert controller.get_team_colors("wsh") == ["FFFFFF", "002D62", "FF0000"]
    
    def test_get_team_colors_unknown_team(self, sample_team_colors):
        controller = LEDController(team_colors_path=str(sample_team_colors))
        
        assert controller.get_team_colors("XYZ") == []
    
    def test_load_team_colors_file_not_found(self, temp_dir):
        controller = LEDController(team_colors_path=str(temp_dir / "nonexistent.json"))
        
        assert controller._team_colors == {}
    
    def test_is_connected_false_initially(self, sample_team_colors):
        controller = LEDController(team_colors_path=str(sample_team_colors))
        
        assert controller.is_connected() is False
    
    @patch('StickCheck.led_controller.serial.Serial')
    def test_connect_success(self, mock_serial, sample_team_colors):
        controller = LEDController(team_colors_path=str(sample_team_colors))
        
        result = controller.connect()
        
        assert result is True
        mock_serial.assert_called_once()
    
    @patch('StickCheck.led_controller.serial.Serial')
    def test_connect_failure(self, mock_serial, sample_team_colors):
        import serial
        mock_serial.side_effect = serial.SerialException("Port not found")
        
        controller = LEDController(team_colors_path=str(sample_team_colors))
        result = controller.connect()
        
        assert result is False
    
    @patch('StickCheck.led_controller.serial.Serial')
    def test_send_command(self, mock_serial, sample_team_colors):
        mock_instance = MagicMock()
        mock_serial.return_value = mock_instance
        
        controller = LEDController(team_colors_path=str(sample_team_colors))
        controller.connect()
        
        result = controller._send_command("I")
        
        assert result is True
        mock_instance.write.assert_called_with(b"I\n")
        mock_instance.flush.assert_called_once()
    
    @patch('StickCheck.led_controller.serial.Serial')
    def test_celebrate(self, mock_serial, sample_team_colors):
        mock_instance = MagicMock()
        mock_serial.return_value = mock_instance
        
        controller = LEDController(team_colors_path=str(sample_team_colors))
        controller.connect()
        
        result = controller.celebrate("WSH")
        
        assert result is True
        mock_instance.write.assert_called_with(b"C:FFFFFF,002D62,FF0000\n")
    
    @patch('StickCheck.led_controller.serial.Serial')
    def test_idle(self, mock_serial, sample_team_colors):
        mock_instance = MagicMock()
        mock_serial.return_value = mock_instance
        
        controller = LEDController(team_colors_path=str(sample_team_colors))
        controller.connect()
        
        result = controller.idle()
        
        assert result is True
        mock_instance.write.assert_called_with(b"I\n")
    
    @patch('StickCheck.led_controller.serial.Serial')
    def test_ping_success(self, mock_serial, sample_team_colors):
        mock_instance = MagicMock()
        mock_instance.readline.return_value = b"PONG\n"
        mock_serial.return_value = mock_instance
        
        controller = LEDController(team_colors_path=str(sample_team_colors))
        controller.connect()
        
        result = controller.ping()
        
        assert result is True
        mock_instance.write.assert_called_with(b"P\n")
    
    @patch('StickCheck.led_controller.serial.Serial')
    def test_ping_failure(self, mock_serial, sample_team_colors):
        mock_instance = MagicMock()
        mock_instance.readline.return_value = b""  # No response
        mock_serial.return_value = mock_instance
        
        controller = LEDController(team_colors_path=str(sample_team_colors))
        controller.connect()
        
        result = controller.ping()
        
        assert result is False
    
    @patch('StickCheck.led_controller.serial.Serial')
    def test_ping_unexpected_response(self, mock_serial, sample_team_colors):
        mock_instance = MagicMock()
        mock_instance.readline.return_value = b"GARBAGE\n"
        mock_serial.return_value = mock_instance
        
        controller = LEDController(team_colors_path=str(sample_team_colors))
        controller.connect()
        
        result = controller.ping()
        
        assert result is False
    
    @patch('StickCheck.led_controller.serial.Serial')
    def test_disconnect(self, mock_serial, sample_team_colors):
        mock_instance = MagicMock()
        mock_instance.is_open = True
        mock_serial.return_value = mock_instance
        
        controller = LEDController(team_colors_path=str(sample_team_colors))
        controller.connect()
        controller.disconnect()
        
        mock_instance.close.assert_called_once()
    
    @patch('StickCheck.led_controller.serial.Serial')
    def test_context_manager(self, mock_serial, sample_team_colors):
        mock_instance = MagicMock()
        mock_instance.is_open = True
        mock_serial.return_value = mock_instance
        
        with LEDController(team_colors_path=str(sample_team_colors)) as controller:
            assert controller.is_connected() is True
        
        mock_instance.close.assert_called_once()
