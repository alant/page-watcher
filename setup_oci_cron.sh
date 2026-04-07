#!/bin/bash

# Setup script for OCI ARM instance launcher cron job
# Runs the launcher every 30 minutes until successful

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LAUNCHER_SCRIPT="$SCRIPT_DIR/oci_arm_launcher.sh"

echo "Setting up OCI ARM instance launcher cron job..."

# Check if launcher script exists
if [ ! -f "$LAUNCHER_SCRIPT" ]; then
    echo "Error: Launcher script not found at $LAUNCHER_SCRIPT"
    exit 1
fi

# Make sure launcher script is executable
chmod +x "$LAUNCHER_SCRIPT"

# Create cron job entry
CRON_ENTRY="*/30 * * * * $LAUNCHER_SCRIPT >> $SCRIPT_DIR/oci_arm_launcher.log 2>&1"

# Check if cron job already exists
if crontab -l 2>/dev/null | grep -q "oci_arm_launcher.sh"; then
    echo "Cron job already exists. Updating..."
    # Remove old entry and add new one
    (crontab -l 2>/dev/null | grep -v "oci_arm_launcher.sh"; echo "$CRON_ENTRY") | crontab -
else
    echo "Adding new cron job..."
    # Add new entry
    (crontab -l 2>/dev/null; echo "$CRON_ENTRY") | crontab -
fi

echo "Cron job installed successfully!"
echo "The launcher will run every 30 minutes until an instance is created."
echo ""
echo "To check status:"
echo "  tail -f $SCRIPT_DIR/oci_arm_launcher.log"
echo ""
echo "To remove the cron job:"
echo "  crontab -e"
echo "  (then delete the line containing 'oci_arm_launcher.sh')"
echo ""
echo "To manually run the launcher:"
echo "  $LAUNCHER_SCRIPT"
