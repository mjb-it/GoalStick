import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


def get_install_dir() -> Path:
    """Get the GoalStick installation directory."""
    # This file is in PythonSrc/StickCheck/, so go up two levels
    return Path(__file__).parent.parent.parent


def is_overlay_active() -> bool:
    """Check if the system is running with an overlay filesystem."""
    try:
        with open("/proc/mounts", "r") as f:
            return "overlayroot" in f.read()
    except Exception:
        return False


def disable_overlay_for_update() -> bool:
    """
    Disable overlay filesystem to allow updates.
    Returns True if overlay was disabled (reboot needed after update).
    Returns False if overlay wasn't active or couldn't be disabled.
    """
    if not is_overlay_active():
        return False
    
    try:
        log.info("Disabling overlay filesystem for update...")
        
        # Write empty overlayroot config to disable it
        result = subprocess.run(
            ["sudo", "bash", "-c", 'echo \'overlayroot=""\' > /etc/overlayroot.conf'],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            log.info("Overlay disabled - reboot required to apply updates")
            return True
        else:
            log.error(f"Failed to disable overlay: {result.stderr}")
            return False
            
    except Exception as e:
        log.error(f"Error disabling overlay: {e}")
        return False


def enable_overlay_after_update() -> bool:
    """Re-enable overlay filesystem after updates are applied."""
    try:
        log.info("Re-enabling overlay filesystem...")
        
        result = subprocess.run(
            ["sudo", "bash", "-c", 'echo \'overlayroot="tmpfs:swap=1,recurse=0"\' > /etc/overlayroot.conf'],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            log.info("Overlay re-enabled - will activate on next reboot")
            return True
        else:
            log.error(f"Failed to re-enable overlay: {result.stderr}")
            return False
            
    except Exception as e:
        log.error(f"Error re-enabling overlay: {e}")
        return False


# Only update from an HTTPS remote. The repository is public so there is no
# credential at stake, but refusing plaintext/git:// transports prevents a
# trivial on-path substitution of the code that will run as root.
ALLOWED_REMOTE_PREFIXES = ("https://",)

# Optional: if this file exists, every update must be signed by one of the
# listed SSH keys (git "allowed signers" format). Create it with e.g.
#   echo "you@example.com ssh-ed25519 AAAA..." | sudo tee /etc/goalstick/update-allowed-signers
# and sign your commits (git config gpg.format ssh; commit.gpgsign true).
ALLOWED_SIGNERS_FILE = Path("/etc/goalstick/update-allowed-signers")


def _git(args: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=get_install_dir(),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _current_branch() -> Optional[str]:
    result = _git(["rev-parse", "--abbrev-ref", "HEAD"])
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch if branch and branch != "HEAD" else None


def _upstream_ref() -> Optional[str]:
    result = _git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _remote_url_allowed() -> bool:
    result = _git(["remote", "get-url", "origin"])
    if result.returncode != 0:
        log.warning("Auto-update: no 'origin' remote configured")
        return False
    url = result.stdout.strip()
    if not url.startswith(ALLOWED_REMOTE_PREFIXES):
        log.error(f"Auto-update refused: remote URL is not HTTPS ({url})")
        return False
    return True


def _verify_commit_signature(ref: str) -> bool:
    """
    Verify `ref` is signed by an allowed signer when the allowed-signers file
    is present. Returns True when verification is not configured.
    """
    if not ALLOWED_SIGNERS_FILE.exists():
        return True
    result = _git([
        "-c", "gpg.format=ssh",
        "-c", f"gpg.ssh.allowedSignersFile={ALLOWED_SIGNERS_FILE}",
        "verify-commit", ref,
    ])
    if result.returncode != 0:
        log.error(f"Auto-update refused: {ref} is not signed by an allowed key: {result.stderr.strip()}")
        return False
    log.info(f"Verified signature on {ref}")
    return True


def check_for_updates() -> bool:
    """
    Check if there are updates available on the tracked upstream branch.
    Returns True if updates are available.
    """
    try:
        if not _remote_url_allowed():
            return False

        result = _git(["fetch", "--prune"], timeout=60)
        if result.returncode != 0:
            log.warning(f"Git fetch failed: {result.stderr.strip()}")
            return False

        upstream = _upstream_ref()
        if not upstream:
            log.warning("Auto-update: current branch has no upstream")
            return False

        # Behind if upstream has commits that HEAD does not.
        result = _git(["rev-list", "--count", f"HEAD..{upstream}"])
        if result.returncode != 0:
            return False
        behind = int(result.stdout.strip() or "0")
        if behind:
            log.info(f"Auto-update: {behind} new commit(s) available on {upstream}")
        return behind > 0

    except Exception as e:
        log.error(f"Error checking for updates: {e}")
        return False


def update_code() -> bool:
    """
    Fast-forward to the upstream branch and reinstall the package.
    Returns True if successful.
    """
    install_dir = get_install_dir()
    venv_pip = install_dir / ".venv" / "bin" / "pip"

    try:
        if not _remote_url_allowed():
            return False

        upstream = _upstream_ref()
        if not upstream:
            log.error("Auto-update: current branch has no upstream")
            return False

        before = _git(["rev-parse", "HEAD"]).stdout.strip()
        target = _git(["rev-parse", upstream]).stdout.strip()
        if not target:
            log.error("Auto-update: could not resolve upstream commit")
            return False

        if before == target:
            log.info("Code is already up to date")
            return True

        if not _verify_commit_signature(target):
            return False

        # Refuse anything that is not a pure fast-forward of our history.
        if _git(["merge-base", "--is-ancestor", "HEAD", target]).returncode != 0:
            log.error("Auto-update refused: upstream history has diverged (not a fast-forward)")
            return False

        log.info(f"Updating {before[:10]} -> {target[:10]} from {upstream}")
        result = _git(["merge", "--ff-only", target], timeout=120)
        if result.returncode != 0:
            log.error(f"Git fast-forward failed: {result.stderr.strip()}")
            return False

        # Reinstall package to pick up any dependency changes
        log.info("Reinstalling package...")
        result = subprocess.run(
            [str(venv_pip), "install", "-e", "PythonSrc[dev]"],
            cwd=install_dir,
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode != 0:
            log.error(f"Pip install failed: {result.stderr}")
            return False

        log.info("Code update complete!")
        return True

    except Exception as e:
        log.error(f"Error updating code: {e}")
        return False


def update_and_restart() -> None:
    """
    Update code and restart the service.
    This function does not return if successful.
    """
    if update_code():
        log.info("Restarting service to apply updates...")
        subprocess.run(
            ["sudo", "systemctl", "restart", "goalstick"],
            capture_output=True,
            text=True
        )
        # If we get here, the restart failed
        log.error("Service restart may have failed")


def check_esp32_changes() -> bool:
    """
    Check if ESP32 code has changed in the latest update.
    Returns True if ESP32 code was modified.
    """
    install_dir = get_install_dir()
    
    try:
        # Check what files changed in the last pull
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD@{1}", "HEAD"],
            cwd=install_dir,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            log.warning("Could not check ESP32 changes")
            return False
        
        # Check if any .ino files changed
        changed_files = result.stdout.strip().split('\n')
        return any('.ino' in f for f in changed_files)
        
    except Exception as e:
        log.error(f"Error checking ESP32 changes: {e}")
        return False


def update_esp32_firmware() -> bool:
    """
    Compile and upload ESP32 firmware using arduino-cli.
    Returns True if successful.
    """
    install_dir = get_install_dir()
    sketch_path = install_dir / "ESP32" / "hockey_stick_light_controller_copy_20260131123701" / "hockey_stick_light_controller"
    
    if not sketch_path.exists():
        log.error(f"ESP32 sketch not found at {sketch_path}")
        return False
    
    try:
        import RPi.GPIO as GPIO
        
        # GPIO pins for ESP32 bootloader control
        BOOT_PIN = 13   # Pi GPIO13 -> ESP32 D9 (GPIO9)
        RESET_PIN = 27  # Pi GPIO27 -> ESP32 D0 (EN)
        
        log.info("Compiling ESP32 firmware...")
        
        # Compile the sketch
        result = subprocess.run(
            ["arduino-cli", "compile", "--fqbn", "esp32:esp32:XIAO_ESP32C3", str(sketch_path)],
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode != 0:
            log.error(f"ESP32 compile failed: {result.stderr}")
            return False
        
        log.info("ESP32 compile successful")
        
        # Enter bootloader mode
        log.info("Entering ESP32 bootloader mode...")
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(BOOT_PIN, GPIO.OUT)
        GPIO.setup(RESET_PIN, GPIO.OUT)
        
        # Bootloader entry sequence
        GPIO.output(BOOT_PIN, GPIO.LOW)   # Hold BOOT low
        time.sleep(0.1)
        GPIO.output(RESET_PIN, GPIO.LOW)  # Assert reset
        time.sleep(0.1)
        GPIO.output(RESET_PIN, GPIO.HIGH) # Release reset
        time.sleep(0.1)
        GPIO.output(BOOT_PIN, GPIO.HIGH)  # Release BOOT
        time.sleep(0.5)  # Wait for bootloader to be ready
        
        # Cleanup GPIO
        GPIO.cleanup([BOOT_PIN, RESET_PIN])
        
        # Upload to ESP32
        log.info("Uploading ESP32 firmware...")
        
        result = subprocess.run(
            ["arduino-cli", "upload", "--fqbn", "esp32:esp32:XIAO_ESP32C3", 
             "--port", "/dev/serial0", str(sketch_path)],
            capture_output=True,
            text=True,
            timeout=120
        )
        
        if result.returncode != 0:
            log.error(f"ESP32 upload failed: {result.stderr}")
            return False
        
        log.info("ESP32 firmware updated successfully")
        
        # Wait for ESP32 to reboot
        time.sleep(3)
        
        return True
        
    except subprocess.TimeoutExpired:
        log.error("ESP32 update timed out")
        return False
    except Exception as e:
        log.error(f"Error updating ESP32: {e}")
        return False


def run_system_updates() -> bool:
    """
    Run system package updates (security patches).
    Returns True if successful.
    """
    try:
        log.info("Running system updates...")
        
        # Update package lists
        result = subprocess.run(
            ["sudo", "apt-get", "update", "-qq"],
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode != 0:
            log.warning(f"apt-get update failed: {result.stderr}")
            return False
        
        # Install security updates only (unattended-upgrades style)
        result = subprocess.run(
            ["sudo", "apt-get", "upgrade", "-y", "-qq", 
             "-o", "Dpkg::Options::=--force-confold",
             "-o", "Dpkg::Options::=--force-confdef"],
            capture_output=True,
            text=True,
            timeout=1800  # 30 minutes max
        )
        
        if result.returncode != 0:
            log.warning(f"apt-get upgrade failed: {result.stderr}")
            return False
        
        log.info("System updates complete")
        return True
        
    except subprocess.TimeoutExpired:
        log.error("System update timed out")
        return False
    except Exception as e:
        log.error(f"Error running system updates: {e}")
        return False
