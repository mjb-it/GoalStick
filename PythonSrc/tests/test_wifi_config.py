import sys
from unittest.mock import MagicMock

import pytest

sys.modules['nhlpy'] = MagicMock()

from StickCheck import wifi_config as wc
from StickCheck.wifi_config import (
    validate_ssid,
    validate_passphrase,
    WifiValidationError,
    build_nm_keyfile,
    build_wpa_conf,
    _split_wpa_conf,
    _keyfile_ssid,
)


class TestValidation:
    def test_valid_ssid(self):
        assert validate_ssid("My Network") == "My Network"
        assert validate_ssid("Café-5G") == "Café-5G"
        assert validate_ssid("a" * 32) == "a" * 32

    @pytest.mark.parametrize("bad", ["", "a" * 33, "has\nnewline", "tab\there", "\x00", "é" * 17, None, 5])
    def test_invalid_ssid(self, bad):
        with pytest.raises(WifiValidationError):
            validate_ssid(bad)

    def test_valid_passphrase(self):
        assert validate_passphrase("password") == "password"
        assert validate_passphrase("p@ss w0rd! \"quoted\" 'single' \\back") == "p@ss w0rd! \"quoted\" 'single' \\back"
        assert validate_passphrase("x" * 63) == "x" * 63
        assert validate_passphrase("ab" * 32) == "ab" * 32  # 64 hex

    @pytest.mark.parametrize("bad", ["short", "x" * 64, "x" * 65, "pass\nword", "pässword", "", None, 123])
    def test_invalid_passphrase(self, bad):
        with pytest.raises(WifiValidationError):
            validate_passphrase(bad)

    def test_configure_wifi_rejects_invalid_without_touching_system(self, monkeypatch):
        touched = []
        monkeypatch.setattr(wc, "_nmcli_available", lambda: touched.append("nmcli") or True)
        monkeypatch.setattr(wc, "_configure_with_nmcli", lambda s, p: touched.append("configured") or True)
        assert wc.configure_wifi("ok", "short") is False
        assert wc.configure_wifi("bad\nssid", "goodpassword") is False
        assert touched == []

    def test_configure_wifi_uses_nmcli_when_present(self, monkeypatch):
        calls = []
        monkeypatch.setattr(wc, "_nmcli_available", lambda: True)
        monkeypatch.setattr(wc, "_configure_with_nmcli", lambda s, p: calls.append(("nm", s, p)) or True)
        monkeypatch.setattr(wc, "_configure_with_wpa_supplicant", lambda s, p: calls.append(("wpa", s, p)) or True)
        assert wc.configure_wifi("Home", "goodpassword") is True
        assert calls == [("nm", "Home", "goodpassword")]

    def test_configure_wifi_falls_back_to_wpa_supplicant_only_without_nmcli(self, monkeypatch):
        calls = []
        monkeypatch.setattr(wc, "_nmcli_available", lambda: False)
        monkeypatch.setattr(wc, "_configure_with_nmcli", lambda s, p: calls.append("nm") or False)
        monkeypatch.setattr(wc, "_configure_with_wpa_supplicant", lambda s, p: calls.append("wpa") or True)
        assert wc.configure_wifi("Home", "goodpassword") is True
        assert calls == ["wpa"]


class TestNetworkManagerKeyfile:
    def test_ssid_encoded_as_bytes(self):
        assert _keyfile_ssid("AB") == "65;66;"
        assert _keyfile_ssid("é") == "195;169;"

    def test_keyfile_contents(self):
        kf = build_nm_keyfile("Home;Net", "p=a;ss\\word", conn_uuid="1234")
        assert "[connection]" in kf
        assert "uuid=1234" in kf
        assert "type=wifi" in kf
        assert "ssid=" + _keyfile_ssid("Home;Net") in kf
        assert "key-mgmt=wpa-psk" in kf
        assert "psk=p=a;ss\\\\word" in kf  # backslash escaped
        assert "autoconnect=true" in kf

    def test_keyfile_leading_space_escaped(self):
        kf = build_nm_keyfile("Net", " leadingspace")
        assert "psk=\\s" + "leadingspace" in kf

    def test_nmcli_backend_writes_0600_and_activates(self, monkeypatch, temp_dir):
        written = {}
        commands = []

        def fake_write(path, content, mode=0o600):
            written["path"] = path
            written["content"] = content
            written["mode"] = mode
            return True

        class Result:
            def __init__(self, rc):
                self.returncode = rc
                self.stderr = ""
                self.stdout = ""

        def fake_run(cmd, **kwargs):
            commands.append(cmd)
            return Result(0)

        monkeypatch.setattr(wc, "write_system_file", fake_write)
        monkeypatch.setattr(wc.subprocess, "run", fake_run)

        assert wc._configure_with_nmcli("Home", "goodpassword") is True
        assert written["mode"] == 0o600
        assert written["path"] == wc.NM_PROFILE_PATH
        assert "psk=goodpassword" in written["content"]
        # The password never appears on any command line
        for cmd in commands:
            assert "goodpassword" not in " ".join(cmd)
        assert any("reload" in cmd for cmd in commands)
        assert any("up" in cmd for cmd in commands)

    def test_nmcli_backend_removes_profile_on_activation_failure(self, monkeypatch):
        commands = []

        class Result:
            def __init__(self, rc):
                self.returncode = rc
                self.stderr = "Secrets were required"
                self.stdout = ""

        def fake_run(cmd, **kwargs):
            commands.append(cmd)
            return Result(1 if "up" in cmd else 0)

        monkeypatch.setattr(wc, "write_system_file", lambda *a, **k: True)
        monkeypatch.setattr(wc.subprocess, "run", fake_run)

        assert wc._configure_with_nmcli("Home", "wrongpassword") is False
        assert any("delete" in cmd for cmd in commands)


class TestWpaSupplicantConf:
    EXISTING = """ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=US

network={
\tssid="Old"
\tpsk=aaaa
}

network={
\tssid="Keep"
\tpsk=bbbb
}
"""

    def test_split(self):
        header, blocks = _split_wpa_conf(self.EXISTING)
        assert "update_config=1" in header
        assert len(blocks) == 2
        assert any('ssid="Old"' in "\n".join(b) for b in blocks)

    def test_replaces_existing_block_for_same_ssid(self):
        out = build_wpa_conf(self.EXISTING, "Old", "c" * 64)
        assert out.count("network={") == 2
        assert 'ssid="Old"' not in out
        assert "ssid=" + "Old".encode().hex() in out
        assert 'ssid="Keep"' in out
        assert "psk=" + "c" * 64 in out
        assert "#psk" not in out

    def test_replaces_existing_hex_block(self):
        existing = "update_config=1\n\nnetwork={\n\tssid=" + "Old".encode().hex() + "\n\tpsk=aaaa\n}\n"
        out = build_wpa_conf(existing, "Old", "c" * 64)
        assert out.count("network={") == 1
        assert "psk=aaaa" not in out

    def test_hostile_ssid_cannot_break_file(self):
        ssid = 'x"\n}\nnetwork={\n\tssid="evil'
        # Not valid per validate_ssid (newlines), but the builder must still be safe
        out = build_wpa_conf(self.EXISTING, ssid, "c" * 64)
        header, blocks = _split_wpa_conf(out)
        assert len(blocks) == 3
        assert "evil" not in out  # only the hex form appears

    def test_fresh_file_has_header(self):
        out = build_wpa_conf(None, "Home", "d" * 64)
        assert out.startswith("ctrl_interface=")
        assert out.count("network={") == 1

    def test_derive_psk_hex_passthrough(self):
        assert wc._derive_psk("Home", "AB" * 32) == "ab" * 32

    def test_derive_psk_uses_stdin(self, monkeypatch):
        seen = {}

        class Result:
            returncode = 0
            stderr = ""
            stdout = 'network={\n\tssid="Home"\n\t#psk="goodpassword"\n\tpsk=' + "e" * 64 + "\n}\n"

        def fake_run(cmd, **kwargs):
            seen["cmd"] = cmd
            seen["input"] = kwargs.get("input")
            return Result()

        monkeypatch.setattr(wc.subprocess, "run", fake_run)
        assert wc._derive_psk("Home", "goodpassword") == "e" * 64
        assert "goodpassword" not in seen["cmd"]
        assert seen["input"].strip() == "goodpassword"
