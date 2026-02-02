#!/bin/bash
# Install GoalStick as a systemd service

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_FILE="$SCRIPT_DIR/goalstick.service"

echo "Installing GoalStick service..."

# Copy service file to systemd
sudo cp "$SERVICE_FILE" /etc/systemd/system/goalstick.service

# Reload systemd
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable goalstick.service

# Start the service
sudo systemctl start goalstick.service

echo ""
echo "GoalStick service installed and started!"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status goalstick    - Check service status"
echo "  sudo systemctl stop goalstick      - Stop the service"
echo "  sudo systemctl start goalstick     - Start the service"
echo "  sudo systemctl restart goalstick   - Restart the service"
echo "  sudo journalctl -u goalstick -f    - View live logs"
