#!/bin/bash

# OCI ARM Instance Launcher
# Attempts to launch an ARM always-free instance every 30 minutes
# Stops when successful and sends notification

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$SCRIPT_DIR/oci_arm_launcher.log"
STATUS_FILE="$SCRIPT_DIR/.oci_arm_status"
SUCCESS_FLAG="$SCRIPT_DIR/.oci_arm_success"

# Load environment variables
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
else
    echo "Error: .env file not found."
    exit 1
fi

# Logging function
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

# Check if already succeeded
if [ -f "$SUCCESS_FLAG" ]; then
    log "ARM instance already created successfully. Exiting."
    exit 0
fi

# Install OCI CLI if needed
if ! command -v oci &> /dev/null; then
    log "OCI CLI not found. Installing..."
    bash -c "$(curl -L https://raw.githubusercontent.com/oracle/oci-cli/master/scripts/install/install.sh)" -- --accept-all-defaults
    export PATH=$PATH:~/bin

    if ! command -v oci &> /dev/null; then
        log "ERROR: Failed to install OCI CLI"
        exit 1
    fi
    log "OCI CLI installed successfully"
fi

# Validate required environment variables
if [ -z "$COMPARTMENT_ID" ] || [ -z "$SUBNET_ID" ] || [ -z "$IMAGE_ID" ] || [ -z "$AD_NAME" ] || [ -z "$DISPLAY_NAME" ]; then
    log "ERROR: Missing required OCI environment variables"
    exit 1
fi

# Prepare SSH key - support both file and direct key from env
if [ -n "$SSH_AUTHORIZED_KEYS" ]; then
    # Use SSH key from environment variable
    log "Using SSH key from SSH_AUTHORIZED_KEYS environment variable"
    SSH_KEY_PARAM="--ssh-authorized-keys"
    SSH_KEY_VALUE="$SSH_AUTHORIZED_KEYS"
else
    # Use SSH key from file
    SSH_KEY_FILE="${SSH_KEY_FILE:-$HOME/.ssh/id_rsa.pub}"
    if [ ! -f "$SSH_KEY_FILE" ]; then
        log "ERROR: SSH public key not found at $SSH_KEY_FILE and SSH_AUTHORIZED_KEYS not set"
        exit 1
    fi
    log "Using SSH key from file: $SSH_KEY_FILE"
    SSH_KEY_PARAM="--ssh-authorized-keys-file"
    SSH_KEY_VALUE="$SSH_KEY_FILE"
fi

log "Attempting to create ARM instance..."

# Update status file
echo "attempting" > "$STATUS_FILE"
echo "$(date +%s)" >> "$STATUS_FILE"

# Attempt to launch instance
oci compute instance launch \
    --availability-domain "$AD_NAME" \
    --compartment-id "$COMPARTMENT_ID" \
    --shape "VM.Standard.A1.Flex" \
    --shape-config '{"ocpus": 4, "memoryInGBs": 24}' \
    --subnet-id "$SUBNET_ID" \
    --image-id "$IMAGE_ID" \
    --display-name "$DISPLAY_NAME" \
    --assign-public-ip true \
    "$SSH_KEY_PARAM" "$SSH_KEY_VALUE" \
    2>&1 | tee /tmp/oci_launch_log.txt

EXIT_CODE=${PIPESTATUS[0]}

if [ $EXIT_CODE -eq 0 ]; then
    log "SUCCESS! ARM instance created."

    # Mark as successful
    echo "success" > "$STATUS_FILE"
    echo "$(date +%s)" >> "$STATUS_FILE"
    touch "$SUCCESS_FLAG"

    # Send notification using existing notify system
    python3 - <<EOF
import sys
sys.path.insert(0, "$SCRIPT_DIR")
from notify import notify
notify("🎉 *OCI ARM Instance Created Successfully!*\n\nInstance: $DISPLAY_NAME\nShape: VM.Standard.A1.Flex (4 OCPUs, 24GB RAM)\n\nThe launcher has stopped running.")
EOF

    exit 0
else
    # Check error type
    if grep -q "Out of host capacity" /tmp/oci_launch_log.txt; then
        log "Out of capacity. Will retry later."
        echo "out_of_capacity" > "$STATUS_FILE"
    elif grep -q "LimitExceeded" /tmp/oci_launch_log.txt; then
        log "Limit exceeded. You may already have instances running."
        echo "limit_exceeded" > "$STATUS_FILE"
    else
        log "ERROR: Unknown error occurred. Check /tmp/oci_launch_log.txt"
        echo "error" > "$STATUS_FILE"
    fi
    echo "$(date +%s)" >> "$STATUS_FILE"

    exit 1
fi
