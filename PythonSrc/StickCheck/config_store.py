import json
import logging
import re
import threading
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict

from .system_files import atomic_write_text

log = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("/etc/goalstick/config.json")
DEFAULT_TEAM = "WSH"
MAX_CELEBRATION_DELAY = 180

# NHL team abbreviations are 2 or 3 uppercase letters.
_TEAM_ABBR_RE = re.compile(r"^[A-Z]{2,3}$")


def is_valid_team_abbr(team_abbr) -> bool:
    return isinstance(team_abbr, str) and bool(_TEAM_ABBR_RE.match(team_abbr))


def normalize_team_abbr(team_abbr) -> Optional[str]:
    """Return the uppercased abbreviation if it is well-formed, else None."""
    if not isinstance(team_abbr, str):
        return None
    candidate = team_abbr.strip().upper()
    return candidate if is_valid_team_abbr(candidate) else None


def clamp_delay(delay) -> int:
    """Coerce a celebration delay to an int in [0, MAX_CELEBRATION_DELAY]."""
    try:
        value = int(delay)
    except (TypeError, ValueError):
        return 0
    return min(MAX_CELEBRATION_DELAY, max(0, value))


@dataclass
class UserConfig:
    team_abbr: str = DEFAULT_TEAM
    celebration_delay_seconds: int = 0  # Delay before triggering lights (0-180)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "UserConfig":
        if not isinstance(data, dict):
            data = {}
        team = normalize_team_abbr(data.get("team_abbr")) or DEFAULT_TEAM
        return cls(
            team_abbr=team,
            celebration_delay_seconds=clamp_delay(data.get("celebration_delay_seconds", 0)),
        )


class ConfigStore:
    """
    Persistent user configuration.

    Saves are atomic (temp file + rename) so a power loss mid-write leaves the
    previous config intact instead of an empty or truncated file.
    """

    def __init__(self, config_path: Path = None):
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self._lock = threading.RLock()
        self._ensure_config_dir()

    def _ensure_config_dir(self) -> None:
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            log.warning(f"Could not create config directory {self.config_path.parent}: {e}")

    def load(self) -> UserConfig:
        with self._lock:
            try:
                if self.config_path.exists():
                    with open(self.config_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    config = UserConfig.from_dict(data)
                    log.info(f"Loaded config: team={config.team_abbr}")
                    return config
                else:
                    log.info("No config file found, using defaults")
                    return UserConfig()
            except (json.JSONDecodeError, IOError, UnicodeDecodeError) as e:
                log.error(f"Error loading config: {e}, using defaults")
                return UserConfig()

    def save(self, config: UserConfig) -> bool:
        with self._lock:
            try:
                self._ensure_config_dir()
                atomic_write_text(self.config_path, json.dumps(config.to_dict(), indent=2) + "\n", mode=0o644)
                log.info(f"Saved config: team={config.team_abbr}")
                return True
            except OSError as e:
                log.error(f"Error saving config: {e}")
                return False

    def set_team(self, team_abbr: str) -> bool:
        team = normalize_team_abbr(team_abbr)
        if team is None:
            log.warning(f"Rejected invalid team abbreviation: {team_abbr!r}")
            return False
        with self._lock:
            config = self.load()
            config.team_abbr = team
            return self.save(config)

    def get_team(self) -> str:
        return self.load().team_abbr

    def set_celebration_delay(self, delay_seconds: int) -> bool:
        with self._lock:
            config = self.load()
            config.celebration_delay_seconds = clamp_delay(delay_seconds)
            return self.save(config)

    def get_celebration_delay(self) -> int:
        return self.load().celebration_delay_seconds

    def update(self, team_abbr: Optional[str] = None, celebration_delay_seconds: Optional[int] = None) -> bool:
        """Apply several changes with a single load/save."""
        with self._lock:
            config = self.load()
            if team_abbr is not None:
                team = normalize_team_abbr(team_abbr)
                if team is None:
                    log.warning(f"Rejected invalid team abbreviation: {team_abbr!r}")
                    return False
                config.team_abbr = team
            if celebration_delay_seconds is not None:
                config.celebration_delay_seconds = clamp_delay(celebration_delay_seconds)
            return self.save(config)
