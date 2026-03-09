import json
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict

log = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("/etc/goalstick/config.json")


@dataclass
class UserConfig:
    team_abbr: str = "WSH"
    celebration_delay_seconds: int = 0  # Delay before triggering lights (0-180)
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "UserConfig":
        return cls(
            team_abbr=data.get("team_abbr", "WSH"),
            celebration_delay_seconds=min(180, max(0, data.get("celebration_delay_seconds", 0)))
        )


class ConfigStore:
    def __init__(self, config_path: Path = None):
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self._ensure_config_dir()
    
    def _ensure_config_dir(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
    
    def load(self) -> UserConfig:
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r') as f:
                    data = json.load(f)
                config = UserConfig.from_dict(data)
                log.info(f"Loaded config: team={config.team_abbr}")
                return config
            else:
                log.info("No config file found, using defaults")
                return UserConfig()
        except (json.JSONDecodeError, IOError) as e:
            log.error(f"Error loading config: {e}, using defaults")
            return UserConfig()
    
    def save(self, config: UserConfig) -> bool:
        try:
            self._ensure_config_dir()
            with open(self.config_path, 'w') as f:
                json.dump(config.to_dict(), f, indent=2)
            log.info(f"Saved config: team={config.team_abbr}")
            return True
        except IOError as e:
            log.error(f"Error saving config: {e}")
            return False
    
    def set_team(self, team_abbr: str) -> bool:
        config = self.load()
        config.team_abbr = team_abbr.upper()
        return self.save(config)
    
    def get_team(self) -> str:
        return self.load().team_abbr
    
    def set_celebration_delay(self, delay_seconds: int) -> bool:
        config = self.load()
        config.celebration_delay_seconds = min(180, max(0, delay_seconds))
        return self.save(config)
    
    def get_celebration_delay(self) -> int:
        return self.load().celebration_delay_seconds
