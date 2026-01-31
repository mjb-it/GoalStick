import serial
import json
import logging
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class LEDConfig:
    serial_port: str = "/dev/serial0"  # Default UART on Raspberry Pi
    baud_rate: int = 115200
    timeout: float = 1.0


class LEDController:
    def __init__(self, config: LEDConfig = None, team_colors_path: str = None):
        self.config = config or LEDConfig()
        self._serial: Optional[serial.Serial] = None
        self._team_colors: dict = {}
        self._load_team_colors(team_colors_path)
    
    def _load_team_colors(self, path: str = None) -> None:
        if path is None:
            # Default to team_colors.json in project root
            path = Path(__file__).parent.parent / "team_colors.json"
        else:
            path = Path(path)
        
        try:
            with open(path, 'r') as f:
                self._team_colors = json.load(f)
            log.info(f"Loaded colors for {len(self._team_colors)} teams")
        except FileNotFoundError:
            log.error(f"Team colors file not found: {path}")
            self._team_colors = {}
        except json.JSONDecodeError as e:
            log.error(f"Invalid JSON in team colors file: {e}")
            self._team_colors = {}
    
    def connect(self) -> bool:
        try:
            self._serial = serial.Serial(
                port=self.config.serial_port,
                baudrate=self.config.baud_rate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.config.timeout
            )
            log.info(f"Connected to ESP32 on {self.config.serial_port}")
            return True
        except serial.SerialException as e:
            log.error(f"Failed to connect to ESP32: {e}")
            return False
    
    def disconnect(self) -> None:
        if self._serial and self._serial.is_open:
            self._serial.close()
            log.info("Disconnected from ESP32")
    
    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open
    
    def get_team_colors(self, team_abbr: str) -> List[str]:
        colors = self._team_colors.get(team_abbr.upper(), [])
        if not colors:
            log.warning(f"No colors found for team: {team_abbr}")
        return colors
    
    def _send_command(self, command: str) -> bool:
        if not self.is_connected():
            log.warning("Not connected to ESP32, attempting to connect...")
            if not self.connect():
                return False
        
        try:
            # Ensure command ends with newline
            if not command.endswith('\n'):
                command += '\n'
            
            self._serial.write(command.encode('utf-8'))
            self._serial.flush()
            log.debug(f"Sent command: {command.strip()}")
            return True
        except serial.SerialException as e:
            log.error(f"Failed to send command: {e}")
            return False
    
    def celebrate(self, team_abbr: str) -> bool:
        colors = self.get_team_colors(team_abbr)
        if not colors:
            log.error(f"Cannot celebrate: no colors for team {team_abbr}")
            return False
        
        # Format: C:RRGGBB,RRGGBB,...
        color_string = ",".join(colors)
        command = f"C:{color_string}"
        
        log.info(f"Triggering celebration for {team_abbr}: {command}")
        return self._send_command(command)
    
    def idle(self) -> bool:
        log.info("Sending idle command to ESP32")
        return self._send_command("I")
    
    def __enter__(self):
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False
