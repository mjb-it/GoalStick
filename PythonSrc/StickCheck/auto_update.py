import logging
import subprocess
import sys
import time
from pathlib import Path

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


def check_for_updates() -> bool:
    """
    Check if there are updates available.
    Returns True if updates are available.
    """
    install_dir = get_install_dir()
    
    try:
        # Fetch latest from remote
        result = subprocess.run(
            ["git", "fetch"],
            cwd=install_dir,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            log.warning(f"Git fetch failed: {result.stderr}")
            return False
        
        # Check if we're behind
        result = subprocess.run(
            ["git", "status", "-uno"],
            cwd=install_dir,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        return "Your branch is behind" in result.stdout
        
    except Exception as e:
        log.error(f"Error checking for updates: {e}")
        return False


def update_code() -> bool:
    """
    Pull latest code and reinstall package.
    Returns True if successful.
    """
    install_dir = get_install_dir()
    venv_pip = install_dir / ".venv" / "bin" / "pip"
    
    try:
        log.info("Pulling latest code...")
        
        # Git pull
        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=install_dir,
            capture_output=True,
            text=True,
            timeout=120
        )
        
        if result.returncode != 0:
            log.error(f"Git pull failed: {result.stderr}")
            return False
        
        if "Already up to date" in result.stdout:
            log.info("Code is already up to date")
            return True
        
        log.info(f"Updated: {result.stdout.strip()}")
        
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
