#!/bin/bash
#
# GoalStick Read-Only Filesystem Setup
# 
# This script configures the Raspberry Pi with an overlay filesystem
# to protect the SD card from corruption due to power loss.
#
# Persistent data (config, WiFi, Bluetooth) is stored on a separate partition.
# Logs go to tmpfs and are lost on reboot.
#
# Run this AFTER make deploy, then reboot.
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    log_error "Please run as root (sudo)"
    exit 1
fi

# Check if already configured
OVERLAY_CONFIGURED="/etc/goalstick/.overlay-configured"
if [ -f "$OVERLAY_CONFIGURED" ]; then
    log_info "Overlay filesystem already configured. Skipping."
    exit 0
fi

log_info "Setting up read-only filesystem for GoalStick..."

# =============================================================================
# Step 1: Install required packages
# =============================================================================
log_info "Step 1: Installing required packages..."

if ! dpkg -l | grep -q "^ii  overlayroot"; then
    apt-get update
    apt-get install -y overlayroot
    log_info "overlayroot installed"
else
    log_info "overlayroot already installed"
fi

# =============================================================================
# Step 2: Create persistent data partition (if not exists)
# =============================================================================
log_info "Step 2: Setting up persistent storage..."

PERSISTENT_DIR="/persistent"
if [ ! -d "$PERSISTENT_DIR" ]; then
    mkdir -p "$PERSISTENT_DIR"
    log_info "Created $PERSISTENT_DIR"
fi

# Create subdirectories for persistent data
mkdir -p "$PERSISTENT_DIR/goalstick"
mkdir -p "$PERSISTENT_DIR/bluetooth"
mkdir -p "$PERSISTENT_DIR/wpa_supplicant"
mkdir -p "$PERSISTENT_DIR/NetworkManager"

# =============================================================================
# Step 3: Move existing config to persistent storage
# =============================================================================
log_info "Step 3: Moving config to persistent storage..."

# GoalStick config
if [ -f "/etc/goalstick/config.json" ] && [ ! -f "$PERSISTENT_DIR/goalstick/config.json" ]; then
    cp /etc/goalstick/config.json "$PERSISTENT_DIR/goalstick/"
    log_info "Copied GoalStick config to persistent storage"
fi

# Bluetooth pairings
if [ -d "/var/lib/bluetooth" ] && [ ! -d "$PERSISTENT_DIR/bluetooth/lib" ]; then
    cp -r /var/lib/bluetooth "$PERSISTENT_DIR/bluetooth/lib"
    log_info "Copied Bluetooth pairings to persistent storage"
fi

# WPA supplicant config
if [ -f "/etc/wpa_supplicant/wpa_supplicant.conf" ] && [ ! -f "$PERSISTENT_DIR/wpa_supplicant/wpa_supplicant.conf" ]; then
    cp /etc/wpa_supplicant/wpa_supplicant.conf "$PERSISTENT_DIR/wpa_supplicant/"
    log_info "Copied WiFi config to persistent storage"
fi

# NetworkManager connections (if using NetworkManager)
if [ -d "/etc/NetworkManager/system-connections" ]; then
    cp -r /etc/NetworkManager/system-connections/* "$PERSISTENT_DIR/NetworkManager/" 2>/dev/null || true
    log_info "Copied NetworkManager connections to persistent storage"
fi

# =============================================================================
# Step 4: Create bind mount service for persistent data
# =============================================================================
log_info "Step 4: Creating systemd mount units..."

# Create mount unit for GoalStick config
cat > /etc/systemd/system/etc-goalstick.mount << 'EOF'
[Unit]
Description=Bind mount for GoalStick config
DefaultDependencies=no
Before=local-fs.target
After=persistent.mount

[Mount]
What=/persistent/goalstick
Where=/etc/goalstick
Type=none
Options=bind

[Install]
WantedBy=local-fs.target
EOF

# Create mount unit for Bluetooth
cat > /etc/systemd/system/var-lib-bluetooth.mount << 'EOF'
[Unit]
Description=Bind mount for Bluetooth pairings
DefaultDependencies=no
Before=local-fs.target bluetooth.service
After=persistent.mount

[Mount]
What=/persistent/bluetooth/lib
Where=/var/lib/bluetooth
Type=none
Options=bind

[Install]
WantedBy=local-fs.target
EOF

# Create mount unit for wpa_supplicant
cat > /etc/systemd/system/etc-wpa_supplicant.mount << 'EOF'
[Unit]
Description=Bind mount for WiFi config
DefaultDependencies=no
Before=local-fs.target wpa_supplicant.service
After=persistent.mount

[Mount]
What=/persistent/wpa_supplicant
Where=/etc/wpa_supplicant
Type=none
Options=bind

[Install]
WantedBy=local-fs.target
EOF

# Enable the mount units
systemctl daemon-reload
systemctl enable etc-goalstick.mount
systemctl enable var-lib-bluetooth.mount
systemctl enable etc-wpa_supplicant.mount

log_info "Mount units created and enabled"

# =============================================================================
# Step 5: Configure tmpfs for logs
# =============================================================================
log_info "Step 5: Configuring tmpfs for logs..."

# Add tmpfs entry for /var/log/goalstick if not already present
if ! grep -q "/var/log/goalstick" /etc/fstab; then
    echo "tmpfs /var/log/goalstick tmpfs defaults,noatime,nosuid,nodev,noexec,mode=0755,size=10M 0 0" >> /etc/fstab
    log_info "Added tmpfs mount for GoalStick logs"
else
    log_info "tmpfs for logs already configured"
fi

# =============================================================================
# Step 6: Configure overlayroot
# =============================================================================
log_info "Step 6: Configuring overlay filesystem..."

# Backup original config
if [ -f /etc/overlayroot.conf ] && [ ! -f /etc/overlayroot.conf.bak ]; then
    cp /etc/overlayroot.conf /etc/overlayroot.conf.bak
fi

# Configure overlayroot to use tmpfs overlay
cat > /etc/overlayroot.conf << 'EOF'
# GoalStick overlay configuration
# Root filesystem is read-only with tmpfs overlay
# Changes are lost on reboot (except for bind-mounted persistent dirs)
overlayroot="tmpfs:swap=1,recurse=0"
EOF

log_info "Overlay filesystem configured"

# =============================================================================
# Step 7: Create helper scripts
# =============================================================================
log_info "Step 7: Creating helper scripts..."

# Script to temporarily disable overlay for updates
cat > /usr/local/bin/goalstick-rw << 'EOF'
#!/bin/bash
# Temporarily remount root as read-write for updates
# Usage: goalstick-rw
#
# After running this, you can make changes. Reboot to return to read-only mode.

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo)"
    exit 1
fi

if grep -q "overlayroot" /proc/mounts; then
    echo "System is running with overlay. To make persistent changes:"
    echo "1. Edit /etc/overlayroot.conf and set overlayroot=\"\""
    echo "2. Reboot"
    echo "3. Make your changes"
    echo "4. Run: sudo goalstick-ro"
    echo "5. Reboot"
else
    echo "System is already in read-write mode."
fi
EOF
chmod +x /usr/local/bin/goalstick-rw

# Script to re-enable overlay
cat > /usr/local/bin/goalstick-ro << 'EOF'
#!/bin/bash
# Re-enable read-only overlay
# Usage: goalstick-ro

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo)"
    exit 1
fi

cat > /etc/overlayroot.conf << 'CONF'
overlayroot="tmpfs:swap=1,recurse=0"
CONF

echo "Overlay re-enabled. Reboot to activate read-only mode."
EOF
chmod +x /usr/local/bin/goalstick-ro

# Script to check overlay status
cat > /usr/local/bin/goalstick-status << 'EOF'
#!/bin/bash
# Check if overlay is active

if grep -q "overlayroot" /proc/mounts; then
    echo "Overlay: ACTIVE (read-only root)"
else
    echo "Overlay: INACTIVE (read-write root)"
fi

echo ""
echo "Persistent mounts:"
mount | grep "/persistent" || echo "  (none active)"
EOF
chmod +x /usr/local/bin/goalstick-status

log_info "Helper scripts created: goalstick-rw, goalstick-ro, goalstick-status"

# =============================================================================
# Step 8: Mark as configured
# =============================================================================
mkdir -p /etc/goalstick
touch "$OVERLAY_CONFIGURED"

log_info ""
log_info "============================================"
log_info "Read-only filesystem setup complete!"
log_info "============================================"
log_info ""
log_info "Persistent data locations:"
log_info "  - GoalStick config: /persistent/goalstick/"
log_info "  - Bluetooth pairings: /persistent/bluetooth/"
log_info "  - WiFi config: /persistent/wpa_supplicant/"
log_info ""
log_info "Helper commands:"
log_info "  - goalstick-status  Check overlay status"
log_info "  - goalstick-rw      Instructions to disable overlay"
log_info "  - goalstick-ro      Re-enable overlay"
log_info ""
log_warn "REBOOT REQUIRED to activate read-only mode!"
log_info ""
