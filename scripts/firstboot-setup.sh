#!/bin/bash
# GoalStick First Boot Setup Script
# 
# This script runs on first boot to install GoalStick and then wipes
# all WiFi credentials so the image can be safely distributed.
#
# Usage:
# 1. Flash Raspberry Pi OS Lite 64-bit with Raspberry Pi Imager
# 2. Configure WiFi and SSH in the imager settings
# 3. Copy this script to /boot/firmware/firstboot-setup.sh
# 4. Add to /boot/firmware/cmdline.txt (same line, at end):
#    systemd.run=/boot/firmware/firstboot-setup.sh systemd.run_success_action=reboot
# 5. Boot the Pi and wait ~10 minutes for setup to complete
# 6. After reboot, WiFi will be wiped - connect via Bluetooth to configure

set -e

LOG_FILE="/var/log/goalstick-firstboot.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=========================================="
echo "GoalStick First Boot Setup"
echo "Started: $(date)"
echo "=========================================="

# Wait for network to be available
echo "Waiting for network..."
for i in {1..60}; do
    if ping -c 1 8.8.8.8 &>/dev/null; then
        echo "Network is up"
        break
    fi
    echo "Waiting for network... ($i/60)"
    sleep 5
done

# Verify network is actually up
if ! ping -c 1 8.8.8.8 &>/dev/null; then
    echo "ERROR: Network not available after 5 minutes"
    echo "Setup cannot continue without network"
    exit 1
fi

# Update package lists
echo "Updating package lists..."
apt-get update

# Install system dependencies
echo "Installing system dependencies..."
apt-get install -y \
    git \
    python3-gi \
    python3-dbus \
    python3-venv \
    python3-pip \
    bluetooth \
    bluez

# Enable UART for ESP32 communication
echo "Enabling UART..."
if ! grep -q "enable_uart=1" /boot/firmware/config.txt; then
    echo "enable_uart=1" >> /boot/firmware/config.txt
fi

# Enable Bluetooth compatibility mode for SPP
echo "Configuring Bluetooth..."
if ! grep -q "ExecStart.*-C" /lib/systemd/system/bluetooth.service; then
    sed -i 's|ExecStart=/usr/libexec/bluetooth/bluetoothd|ExecStart=/usr/libexec/bluetooth/bluetoothd -C|' /lib/systemd/system/bluetooth.service
fi

# Add SP profile
if ! grep -q "ExecStartPost.*sdptool" /lib/systemd/system/bluetooth.service; then
    sed -i '/ExecStart=/a ExecStartPost=/usr/bin/sdptool add SP' /lib/systemd/system/bluetooth.service
fi

# Disable audio plugins in BlueZ to prevent Android from treating device as headset
echo "Disabling Bluetooth audio plugins..."
mkdir -p /etc/bluetooth
if [ ! -f /etc/bluetooth/main.conf ] || ! grep -q "DisablePlugins" /etc/bluetooth/main.conf; then
    cat >> /etc/bluetooth/main.conf << 'EOF'

# Disable audio plugins - GoalStick is not an audio device
[General]
DisablePlugins = a2dp,avrcp
EOF
fi

systemctl daemon-reload

# Clone GoalStick repository
echo "Cloning GoalStick repository..."
cd /tmp
rm -rf GoalStick
git clone https://github.com/mjb-it/GoalStick.git
cd GoalStick

# Run deployment
echo "Deploying GoalStick..."
make deploy

# Stop the service before wiping WiFi (it needs network for updates)
echo "Stopping GoalStick service temporarily..."
systemctl stop goalstick.service || true

# ==========================================
# WIPE ALL WIFI CREDENTIALS
# ==========================================
echo ""
echo "=========================================="
echo "WIPING ALL WIFI CREDENTIALS"
echo "=========================================="

# Remove wpa_supplicant configuration
echo "Removing wpa_supplicant config..."
rm -f /etc/wpa_supplicant/wpa_supplicant.conf
rm -f /etc/wpa_supplicant/wpa_supplicant-wlan0.conf

# Remove NetworkManager connections (if using NetworkManager)
echo "Removing NetworkManager WiFi connections..."
rm -f /etc/NetworkManager/system-connections/*.nmconnection 2>/dev/null || true
rm -rf /etc/NetworkManager/system-connections/* 2>/dev/null || true

# Clear dhcpcd lease files
echo "Clearing DHCP leases..."
rm -f /var/lib/dhcpcd/*.lease 2>/dev/null || true

# Remove any WiFi config from /boot
echo "Removing WiFi config from boot partition..."
rm -f /boot/wpa_supplicant.conf 2>/dev/null || true
rm -f /boot/firmware/wpa_supplicant.conf 2>/dev/null || true

# Clear command history that might contain passwords
echo "Clearing command history..."
rm -f /root/.bash_history
rm -f /home/*/.bash_history 2>/dev/null || true
history -c 2>/dev/null || true

echo "WiFi credentials wiped successfully"
echo ""

# ==========================================
# CLEANUP
# ==========================================
echo "Cleaning up..."

# Remove the firstboot script
rm -f /boot/firstboot-setup.sh
rm -f /boot/firmware/firstboot-setup.sh

# Remove the systemd.run parameter from cmdline.txt
echo "Removing firstboot trigger from cmdline.txt..."
if [ -f /boot/firmware/cmdline.txt ]; then
    sed -i 's| systemd.run=[^ ]*||g' /boot/firmware/cmdline.txt
    sed -i 's| systemd.run_success_action=[^ ]*||g' /boot/firmware/cmdline.txt
elif [ -f /boot/cmdline.txt ]; then
    sed -i 's| systemd.run=[^ ]*||g' /boot/cmdline.txt
    sed -i 's| systemd.run_success_action=[^ ]*||g' /boot/cmdline.txt
fi

# Clean up temp files
rm -rf /tmp/GoalStick

# Re-enable the service (it will start after reboot, but won't have network)
systemctl enable goalstick.service

echo ""
echo "=========================================="
echo "GoalStick First Boot Setup Complete!"
echo "Finished: $(date)"
echo "=========================================="
echo ""
echo "IMPORTANT: WiFi has been wiped!"
echo "After reboot, use the GoalStick Android app"
echo "to configure WiFi via Bluetooth."
echo ""
echo "The device will reboot in 10 seconds..."
sleep 10

reboot
