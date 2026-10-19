import sys
from unittest.mock import MagicMock

import pytest

sys.modules['nhlpy'] = MagicMock()

from StickCheck import system_files as sf


class TestAtomicWrite:
    def test_writes_content(self, temp_dir):
        target = temp_dir / "sub" / "file.txt"
        sf.atomic_write_text(target, "hello\n")
        assert target.read_text() == "hello\n"

    def test_replaces_existing(self, temp_dir):
        target = temp_dir / "file.txt"
        target.write_text("old")
        sf.atomic_write_text(target, "new")
        assert target.read_text() == "new"

    def test_no_temp_files_left(self, temp_dir):
        target = temp_dir / "file.txt"
        sf.atomic_write_text(target, "x")
        assert [p.name for p in temp_dir.iterdir()] == ["file.txt"]

    def test_failure_leaves_original_and_cleans_temp(self, temp_dir, monkeypatch):
        target = temp_dir / "file.txt"
        target.write_text("original")

        def boom(src, dst):
            raise OSError("replace failed")

        monkeypatch.setattr(sf.os, "replace", boom)
        with pytest.raises(OSError):
            sf.atomic_write_text(target, "new")
        assert target.read_text() == "original"
        assert [p.name for p in temp_dir.iterdir()] == ["file.txt"]


class TestWriteSystemFile:
    def test_direct_write_when_permitted(self, temp_dir):
        target = temp_dir / "etc" / "conf"
        assert sf.write_system_file(target, "data", mode=0o600) is True
        assert target.read_text() == "data"

    def test_falls_back_to_sudo_install_on_permission_error(self, temp_dir, monkeypatch):
        target = temp_dir / "conf"
        commands = []

        def denied(path, content, mode=0o600):
            raise PermissionError("nope")

        class Result:
            returncode = 0
            stderr = ""

        def fake_run(cmd, **kwargs):
            commands.append(cmd)
            return Result()

        monkeypatch.setattr(sf, "atomic_write_text", denied)
        monkeypatch.setattr(sf.subprocess, "run", fake_run)

        assert sf.write_system_file(target, "secret", mode=0o600) is True
        install = [c for c in commands if "install" in c][0]
        assert install[:2] == ["sudo", "install"]
        assert "600" in install
        assert "--" in install  # no option injection from the path
        # Staged temp file must be gone afterwards
        tmp_path = install[install.index("--") + 1]
        import os
        assert not os.path.exists(tmp_path)

    def test_returns_false_on_install_failure(self, temp_dir, monkeypatch):
        def denied(path, content, mode=0o600):
            raise PermissionError("nope")

        class Result:
            returncode = 1
            stderr = "install: cannot create"

        monkeypatch.setattr(sf, "atomic_write_text", denied)
        monkeypatch.setattr(sf.subprocess, "run", lambda cmd, **k: Result())
        assert sf.write_system_file(temp_dir / "conf", "secret") is False


class TestRemoveSystemPath:
    def test_removes_directory(self, temp_dir):
        d = temp_dir / "AA-BB-CC-DD-EE-FF"
        d.mkdir()
        (d / "info").write_text("x")
        assert sf.remove_system_path(d) is True
        assert not d.exists()

    def test_missing_is_ok(self, temp_dir):
        assert sf.remove_system_path(temp_dir / "nothing") is True

    def test_refuses_symlink(self, temp_dir):
        real = temp_dir / "real"
        real.mkdir()
        (real / "keep").write_text("x")
        link = temp_dir / "link"
        try:
            link.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not available")
        assert sf.remove_system_path(link) is False
        assert (real / "keep").exists()
