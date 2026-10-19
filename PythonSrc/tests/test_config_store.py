import pytest
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Mock nhlpy before any StickCheck imports
sys.modules['nhlpy'] = MagicMock()

from StickCheck.config_store import ConfigStore, UserConfig


class TestUserConfig:
    def test_default_values(self):
        config = UserConfig()
        assert config.team_abbr == "WSH"
    
    def test_custom_values(self):
        config = UserConfig(team_abbr="TOR")
        assert config.team_abbr == "TOR"
    
    def test_to_dict(self):
        config = UserConfig(team_abbr="BOS")
        result = config.to_dict()
        assert result == {"team_abbr": "BOS", "celebration_delay_seconds": 0}
    
    def test_from_dict(self):
        data = {"team_abbr": "NYR"}
        config = UserConfig.from_dict(data)
        assert config.team_abbr == "NYR"
    
    def test_from_dict_missing_key(self):
        data = {}
        config = UserConfig.from_dict(data)
        assert config.team_abbr == "WSH"  # Default

    def test_from_dict_invalid_team_falls_back(self):
        assert UserConfig.from_dict({"team_abbr": "not a team"}).team_abbr == "WSH"
        assert UserConfig.from_dict({"team_abbr": 42}).team_abbr == "WSH"
        assert UserConfig.from_dict({"team_abbr": "tor"}).team_abbr == "TOR"

    def test_from_dict_clamps_delay(self):
        assert UserConfig.from_dict({"celebration_delay_seconds": 999}).celebration_delay_seconds == 180
        assert UserConfig.from_dict({"celebration_delay_seconds": -5}).celebration_delay_seconds == 0
        assert UserConfig.from_dict({"celebration_delay_seconds": "abc"}).celebration_delay_seconds == 0
        assert UserConfig.from_dict({"celebration_delay_seconds": "30"}).celebration_delay_seconds == 30

    def test_from_dict_non_dict(self):
        assert UserConfig.from_dict(["nope"]).team_abbr == "WSH"


class TestConfigStore:
    def test_load_no_file(self, temp_config_file):
        store = ConfigStore(config_path=temp_config_file)
        config = store.load()
        assert config.team_abbr == "WSH"  # Default
    
    def test_save_and_load(self, temp_config_file):
        store = ConfigStore(config_path=temp_config_file)
        
        config = UserConfig(team_abbr="TOR")
        assert store.save(config) is True
        
        loaded = store.load()
        assert loaded.team_abbr == "TOR"
    
    def test_set_team(self, temp_config_file):
        store = ConfigStore(config_path=temp_config_file)
        
        assert store.set_team("BOS") is True
        assert store.get_team() == "BOS"
    
    def test_set_team_uppercase(self, temp_config_file):
        store = ConfigStore(config_path=temp_config_file)
        
        store.set_team("nyr")
        assert store.get_team() == "NYR"
    
    def test_get_team_default(self, temp_config_file):
        store = ConfigStore(config_path=temp_config_file)
        assert store.get_team() == "WSH"
    
    def test_creates_parent_directory(self, temp_dir):
        nested_path = temp_dir / "subdir" / "config.json"
        store = ConfigStore(config_path=nested_path)
        
        config = UserConfig(team_abbr="CHI")
        assert store.save(config) is True
        assert nested_path.exists()
    
    def test_load_corrupted_json(self, temp_config_file):
        # Write invalid JSON
        with open(temp_config_file, 'w') as f:
            f.write("not valid json {{{")
        
        store = ConfigStore(config_path=temp_config_file)
        config = store.load()
        assert config.team_abbr == "WSH"  # Falls back to default

    def test_set_team_rejects_invalid(self, temp_config_file):
        store = ConfigStore(config_path=temp_config_file)
        store.set_team("TOR")
        assert store.set_team("rm -rf /") is False
        assert store.set_team("") is False
        assert store.set_team(None) is False
        assert store.get_team() == "TOR"

    def test_save_is_atomic_no_temp_left_behind(self, temp_config_file):
        store = ConfigStore(config_path=temp_config_file)
        assert store.save(UserConfig(team_abbr="NYR")) is True
        leftovers = [p for p in temp_config_file.parent.iterdir() if p.name != temp_config_file.name]
        assert leftovers == []
        assert json.loads(temp_config_file.read_text())["team_abbr"] == "NYR"

    def test_save_failure_keeps_previous_file(self, temp_config_file, monkeypatch):
        store = ConfigStore(config_path=temp_config_file)
        store.save(UserConfig(team_abbr="NYR"))

        import StickCheck.config_store as cs
        def boom(*a, **k):
            raise OSError("disk full")
        monkeypatch.setattr(cs, "atomic_write_text", boom)

        assert store.save(UserConfig(team_abbr="BOS")) is False
        assert store.get_team() == "NYR"

    def test_update_single_write(self, temp_config_file):
        store = ConfigStore(config_path=temp_config_file)
        assert store.update(team_abbr="chi", celebration_delay_seconds=45) is True
        loaded = store.load()
        assert loaded.team_abbr == "CHI"
        assert loaded.celebration_delay_seconds == 45
        assert store.update(team_abbr="bad team") is False
        assert store.get_team() == "CHI"
