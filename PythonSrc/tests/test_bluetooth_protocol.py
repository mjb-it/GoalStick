import json
import sys
from unittest.mock import MagicMock

import pytest

# Mock nhlpy before any StickCheck imports
sys.modules['nhlpy'] = MagicMock()

from StickCheck.bluetooth_server import (
    MessageFramer,
    FramingError,
    CommandHandler,
    encode_response,
    TEST_GOAL_MIN_INTERVAL,
)
from StickCheck.config_store import ConfigStore


class TestMessageFramer:
    def test_single_newline_delimited(self):
        f = MessageFramer()
        assert f.feed(b'{"type":"ping"}\n') == [{"type": "ping"}]

    def test_legacy_bare_object(self):
        f = MessageFramer()
        assert f.feed(b'{"type":"ping"}') == [{"type": "ping"}]

    def test_fragmented_across_reads(self):
        f = MessageFramer()
        assert f.feed(b'{"type":"con') == []
        assert f.feed(b'fig","team_abbr":"TOR"}') == [{"type": "config", "team_abbr": "TOR"}]

    def test_two_messages_in_one_read(self):
        f = MessageFramer()
        msgs = f.feed(b'{"type":"get_config"}{"type":"test_goal"}\n')
        assert msgs == [{"type": "get_config"}, {"type": "test_goal"}]

    def test_two_newline_messages_in_one_read(self):
        f = MessageFramer()
        msgs = f.feed(b'{"type":"a"}\n{"type":"b"}\n')
        assert msgs == [{"type": "a"}, {"type": "b"}]

    def test_non_json_line_discarded(self):
        f = MessageFramer()
        assert f.feed(b'hello there\n{"type":"ping"}\n') == [{"type": "ping"}]

    def test_non_object_json_ignored(self):
        f = MessageFramer()
        assert f.feed(b'123\n"str"\n{"type":"ping"}\n') == [{"type": "ping"}]

    def test_oversize_message_raises(self):
        f = MessageFramer(max_message_bytes=64)
        with pytest.raises(FramingError):
            f.feed(b'{"type":"' + b'x' * 100)

    def test_garbage_without_newline_eventually_raises(self):
        f = MessageFramer(max_message_bytes=32)
        with pytest.raises(FramingError):
            for _ in range(10):
                f.feed(b'not json ' * 2)

    def test_split_multibyte_utf8(self):
        f = MessageFramer()
        payload = json.dumps({"type": "config", "wifi_ssid": "Café"}, ensure_ascii=False).encode("utf-8")
        split = payload.index("é".encode("utf-8")) + 1  # split inside the 2-byte char
        assert f.feed(payload[:split]) == []
        assert f.feed(payload[split:] + b"\n") == [{"type": "config", "wifi_ssid": "Café"}]

    def test_invalid_utf8_raises(self):
        f = MessageFramer()
        with pytest.raises(FramingError):
            f.feed(b'{"type":"\xff\xfe\xfd\xfc\xfb"}\n')

    def test_whitespace_only_ignored(self):
        f = MessageFramer()
        assert f.feed(b"\r\n  \n") == []

    def test_encode_response_newline_terminated(self):
        out = encode_response({"status": "ok"})
        assert out.endswith(b"\n")
        assert json.loads(out) == {"status": "ok"}


@pytest.fixture
def store(temp_config_file):
    return ConfigStore(config_path=temp_config_file)


@pytest.fixture
def led():
    led = MagicMock()
    led.known_teams.return_value = ["WSH", "TOR", "BOS"]
    led.celebrate.return_value = True
    return led


@pytest.fixture
def handler(store, led):
    h = CommandHandler(led_controller=led, config_store=store, allow_wifi=False)
    h._get_ip_address = lambda: "10.0.0.5"
    return h


class TestCommandHandler:
    def test_ping(self, handler):
        assert handler.handle({"type": "ping"}) == {"status": "ok", "type": "pong"}

    def test_unknown_type(self, handler):
        resp = handler.handle({"type": "reboot"})
        assert resp["status"] == "error"

    def test_missing_type(self, handler):
        assert handler.handle({})["status"] == "error"
        assert handler.handle({"type": 5})["status"] == "error"

    def test_get_config(self, handler, store):
        store.set_team("TOR")
        resp = handler.handle({"type": "get_config"})
        assert resp["status"] == "ok"
        assert resp["config"]["team_abbr"] == "TOR"
        assert resp["config"]["celebration_delay_seconds"] == 0
        assert resp["config"]["ip_address"] == "10.0.0.5"

    def test_test_goal_uses_configured_team(self, handler, store, led):
        store.set_team("BOS")
        assert handler.handle({"type": "test_goal"})["status"] == "ok"
        led.celebrate.assert_called_once_with("BOS")

    def test_test_goal_rate_limited(self, handler, led):
        assert handler.handle({"type": "test_goal"})["status"] == "ok"
        assert handler.handle({"type": "test_goal"})["status"] == "error"
        assert led.celebrate.call_count == 1
        handler._last_test_goal -= TEST_GOAL_MIN_INTERVAL + 1
        assert handler.handle({"type": "test_goal"})["status"] == "ok"

    def test_test_goal_without_led(self, store):
        h = CommandHandler(led_controller=None, config_store=store)
        assert h.handle({"type": "test_goal"})["status"] == "error"

    def test_config_updates_team_and_delay(self, handler, store):
        resp = handler.handle({"type": "config", "team_abbr": "tor", "celebration_delay_seconds": 30})
        assert resp["status"] == "ok"
        assert resp["wifi"] == "skipped"
        assert store.get_team() == "TOR"
        assert store.get_celebration_delay() == 30

    def test_config_rejects_unknown_team(self, handler, store):
        store.set_team("WSH")
        resp = handler.handle({"type": "config", "team_abbr": "ZZZ"})
        assert resp["status"] == "error"
        assert store.get_team() == "WSH"

    def test_config_rejects_malformed_team(self, handler, store):
        store.set_team("WSH")
        for bad in ("", "T", "TORONTO", "../x", 12, None):
            resp = handler.handle({"type": "config", "team_abbr": bad})
            if bad is None:
                assert resp["status"] == "ok"  # absent = unchanged
            else:
                assert resp["status"] == "error", bad
        assert store.get_team() == "WSH"

    def test_config_missing_team_keeps_current(self, handler, store):
        store.set_team("BOS")
        resp = handler.handle({"type": "config", "celebration_delay_seconds": 10})
        assert resp["status"] == "ok"
        assert store.get_team() == "BOS"
        assert store.get_celebration_delay() == 10

    def test_config_clamps_delay(self, handler, store):
        handler.handle({"type": "config", "celebration_delay_seconds": 9999})
        assert store.get_celebration_delay() == 180

    def test_config_rejects_bad_delay(self, handler):
        assert handler.handle({"type": "config", "celebration_delay_seconds": "lots"})["status"] == "error"
        assert handler.handle({"type": "config", "celebration_delay_seconds": True})["status"] == "error"
        assert handler.handle({"type": "config", "celebration_delay_seconds": [1]})["status"] == "error"

    def test_wifi_refused_outside_pairing_mode(self, handler, store, monkeypatch):
        import StickCheck.wifi_config as wc
        called = []
        monkeypatch.setattr(wc, "configure_wifi", lambda s, p: called.append((s, p)) or True)
        resp = handler.handle({"type": "config", "team_abbr": "TOR",
                               "wifi_ssid": "Home", "wifi_password": "secret123"})
        assert resp["status"] == "error"
        assert called == []
        assert store.get_team() == "WSH"  # nothing applied

    def test_wifi_applied_in_pairing_mode(self, store, led, monkeypatch):
        import StickCheck.wifi_config as wc
        called = []
        monkeypatch.setattr(wc, "configure_wifi", lambda s, p: called.append((s, p)) or True)
        received = []
        h = CommandHandler(led_controller=led, config_store=store, allow_wifi=True,
                           on_config_received=received.append)
        resp = h.handle({"type": "config", "team_abbr": "TOR",
                         "wifi_ssid": "Home", "wifi_password": "secret123"})
        assert resp == {"status": "ok", "wifi": "ok"}
        assert called == [("Home", "secret123")]
        assert store.get_team() == "TOR"
        assert len(received) == 1
        assert received[0].wifi_ssid == "Home"
        assert received[0].team_abbr == "TOR"
        assert h.last_received_config is received[0]

    def test_wifi_failure_reported(self, store, led, monkeypatch):
        import StickCheck.wifi_config as wc
        monkeypatch.setattr(wc, "configure_wifi", lambda s, p: False)
        h = CommandHandler(led_controller=led, config_store=store, allow_wifi=True)
        resp = h.handle({"type": "config", "team_abbr": "TOR",
                         "wifi_ssid": "Home", "wifi_password": "secret123"})
        assert resp["status"] == "error"
        assert store.get_team() == "TOR"  # team still saved so the user can retry wifi only

    def test_wifi_invalid_credentials_rejected_before_configure(self, store, led, monkeypatch):
        import StickCheck.wifi_config as wc
        called = []
        monkeypatch.setattr(wc, "configure_wifi", lambda s, p: called.append(1) or True)
        h = CommandHandler(led_controller=led, config_store=store, allow_wifi=True)
        resp = h.handle({"type": "config", "wifi_ssid": "Home\n", "wifi_password": "secret123"})
        assert resp["status"] == "error"
        resp = h.handle({"type": "config", "wifi_ssid": "Home", "wifi_password": "short"})
        assert resp["status"] == "error"
        assert called == []

    def test_handler_exception_becomes_error_response(self, handler, led):
        led.celebrate.side_effect = RuntimeError("serial exploded")
        resp = handler.handle({"type": "test_goal"})
        assert resp["status"] == "error"
