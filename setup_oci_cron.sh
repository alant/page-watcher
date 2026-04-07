#!/bin/bash

# Setup script for OCI ARM instance launcher systemd service
# Integrates with the existing Page Watcher service architecture

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_FILE="$SCRIPT_DIR/oci-arm-launcher.service"
LAUNCHER_SCRIPT="$SCRIPT_DIR/oci_arm_launcher.sh"

echo "Setting up OCI ARM instance launcher systemd service..."

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo "Please run this script as a regular user (it will use sudo when needed)"
    exit 1
fi

# Check if launcher script exists
if [ ! -f "$LAUNCHER_SCRIPT" ]; then
    echo "Error: Launcher script not found at $LAUNCHER_SCRIPT"
    exit 1
fi

# Check if service file exists
if [ ! -f "$SERVICE_FILE" ]; then
    echo "Error: Service file not found at $SERVICE_FILE"
    exit 1
fi

# Make sure launcher script is executable
chmod +x "$LAUNCHER_SCRIPT"

# Update service file with correct paths (replace /home/ubuntu with actual path)
ACTUAL_PATH="$SCRIPT_DIR"
ACTUAL_USER="$USER"

# Create temporary service file with correct paths
TMP_SERVICE="/tmp/oci-arm-launcher.service"
sed -e "s|/home/ubuntu/page-watcher|$ACTUAL_PATH|g" \
    -e "s|User=ubuntu|User=$ACTUAL_USER|g" \
    "$SERVICE_FILE" > "$TMP_SERVICE"

# Install service file
echo "Installing systemd service..."
sudo cp "$TMP_SERVICE" /etc/systemd/system/oci-arm-launcher.service
rm "$TMP_SERVICE"

# Reload systemd
sudo systemctl daemon-reload

# Enable and start service
echo "Enabling and starting service..."
sudo systemctl enable oci-arm-launcher
sudo systemctl start oci-arm-launcher

echo ""
echo "OCI ARM launcher service installed successfully!"
echo ""
echo "The launcher will run every 30 minutes until an instance is created."
echo ""
echo "Check status:"
echo "  sudo systemctl status oci-arm-launcher"
echo "  sudo journalctl -u oci-arm-launcher -f"
echo "  tail -f $SCRIPT_DIR/oci_arm_launcher.log"
echo ""
echo "Stop the service:"
echo "  sudo systemctl stop oci-arm-launcher"
echo ""
echo "Disable the service:"
echo "  sudo systemctl disable oci-arm-launcher"

