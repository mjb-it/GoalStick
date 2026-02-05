import pytest
import tempfile
import json
from pathlib import Path


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_config_file(temp_dir):
    """Create a temporary config file path."""
    return temp_dir / "config.json"


@pytest.fixture
def sample_team_colors(temp_dir):
    """Create a sample team_colors.json file."""
    colors = {
        "WSH": ["FFFFFF", "002D62", "FF0000"],
        "TOR": ["FFFFFF", "003876"],
        "BOS": ["FFFFFF", "FFC422", "231F20"]
    }
    colors_file = temp_dir / "team_colors.json"
    with open(colors_file, 'w') as f:
        json.dump(colors, f)
    return colors_file
