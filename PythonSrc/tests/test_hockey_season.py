import pytest
import sys
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock

# Mock nhlpy before any StickCheck imports
sys.modules['nhlpy'] = MagicMock()

from StickCheck.scheduler import HockeySeasonDetector


class TestHockeySeasonDetector:
    def test_october_is_hockey_season(self):
        date = datetime(2025, 10, 15)
        assert HockeySeasonDetector.is_hockey_season(date) is True
    
    def test_november_is_hockey_season(self):
        date = datetime(2025, 11, 1)
        assert HockeySeasonDetector.is_hockey_season(date) is True
    
    def test_december_is_hockey_season(self):
        date = datetime(2025, 12, 25)
        assert HockeySeasonDetector.is_hockey_season(date) is True
    
    def test_january_is_hockey_season(self):
        date = datetime(2026, 1, 15)
        assert HockeySeasonDetector.is_hockey_season(date) is True
    
    def test_february_is_hockey_season(self):
        date = datetime(2026, 2, 14)
        assert HockeySeasonDetector.is_hockey_season(date) is True
    
    def test_march_is_hockey_season(self):
        date = datetime(2026, 3, 1)
        assert HockeySeasonDetector.is_hockey_season(date) is True
    
    def test_april_is_hockey_season(self):
        date = datetime(2026, 4, 15)
        assert HockeySeasonDetector.is_hockey_season(date) is True
    
    def test_may_is_hockey_season(self):
        date = datetime(2026, 5, 20)
        assert HockeySeasonDetector.is_hockey_season(date) is True
    
    def test_june_is_hockey_season(self):
        date = datetime(2026, 6, 15)
        assert HockeySeasonDetector.is_hockey_season(date) is True
    
    def test_july_is_not_hockey_season(self):
        date = datetime(2026, 7, 4)
        assert HockeySeasonDetector.is_hockey_season(date) is False
    
    def test_august_is_not_hockey_season(self):
        date = datetime(2026, 8, 15)
        assert HockeySeasonDetector.is_hockey_season(date) is False
    
    def test_early_september_is_not_hockey_season(self):
        date = datetime(2026, 9, 10)
        assert HockeySeasonDetector.is_hockey_season(date) is False
    
    def test_mid_september_is_hockey_season(self):
        date = datetime(2026, 9, 15)
        assert HockeySeasonDetector.is_hockey_season(date) is True
    
    def test_late_september_is_hockey_season(self):
        date = datetime(2026, 9, 25)
        assert HockeySeasonDetector.is_hockey_season(date) is True
    
    def test_default_uses_current_date(self):
        # Should not raise an exception
        result = HockeySeasonDetector.is_hockey_season()
        assert isinstance(result, bool)
