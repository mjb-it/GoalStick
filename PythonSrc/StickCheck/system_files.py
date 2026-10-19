"""
Helpers for safely writing files that may contain secrets or that live in
system directories (e.g. /etc).

Design goals:
- Never write secrets to a predictable, world-readable temp path.
- Never leave a half-written file behind on power loss (write temp + atomic
  rename within the destination directory).
- Work when running as root (the normal systemd case) and fall back to sudo
  when running as an unprivileged developer.
"""

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


def atomic_write_text(path: Path, content: str, mode: int = 0o600) -> None:
    """
    Atomically write `content` to `path` with the given permission mode.

    The data is written to a uniquely named temp file in the same directory,
    fsync'd, chmod'd, then renamed over the destination. Readers either see
    the old file or the complete new file, never a partial one.

    Raises OSError (including PermissionError) on failure.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise

    # Best effort: persist the directory entry too.
    try:
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass


def write_system_file(path: Path, content: str, mode: int = 0o600) -> bool:
    """
    Write a file that normally requires root (e.g. under /etc).

    When running as root this is a direct atomic write. Otherwise the content
    is staged in a private (0600, unpredictable name) temp file and installed
    with `sudo install`, which also sets the mode and never follows symlinks
    at the destination.

    Returns True on success.
    """
    path = Path(path)
    try:
        atomic_write_text(path, content, mode)
        return True
    except PermissionError:
        pass
    except OSError as e:
        log.error(f"Failed to write {path}: {e}")
        return False

    # Unprivileged fallback.
    tmp: Optional[tempfile.NamedTemporaryFile] = None
    try:
        tmp = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, prefix="goalstick-", suffix=".tmp")
        tmp.write(content)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.chmod(tmp.name, 0o600)

        subprocess.run(["sudo", "mkdir", "-p", str(path.parent)], capture_output=True, timeout=10)
        result = subprocess.run(
            ["sudo", "install", "-m", f"{mode:o}", "-o", "root", "-g", "root", "--", tmp.name, str(path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            log.error(f"Failed to install {path}: {result.stderr.strip()}")
            return False
        return True
    except Exception as e:
        log.error(f"Failed to write {path} via sudo: {e}")
        return False
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass


def remove_system_path(path: Path) -> bool:
    """
    Remove a file or directory tree, refusing to follow a symlink at `path`.

    Falls back to `sudo rm -rf -- path` when not running as root.
    Returns True if the path no longer exists.
    """
    path = Path(path)
    if not path.exists() and not path.is_symlink():
        return True
    if path.is_symlink():
        log.warning(f"Refusing to remove symlink {path}")
        return False

    try:
        if path.is_dir():
            import shutil
            shutil.rmtree(path)
        else:
            path.unlink()
        return True
    except PermissionError:
        pass
    except OSError as e:
        log.error(f"Failed to remove {path}: {e}")
        return False

    result = subprocess.run(
        ["sudo", "rm", "-rf", "--one-file-system", "--", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        log.error(f"Failed to remove {path}: {result.stderr.strip()}")
        return False
    return True
