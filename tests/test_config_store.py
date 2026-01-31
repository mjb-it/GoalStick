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
        assert result == {"team_abbr": "BOS"}
    
    def test_from_dict(self):
        data = {"team_abbr": "NYR"}
        config = UserConfig.from_dict(data)
        assert config.team_abbr == "NYR"
    
    def test_from_dict_missing_key(self):
        data = {}
        config = UserConfig.from_dict(data)
        assert config.team_abbr == "WSH"  # Default


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
