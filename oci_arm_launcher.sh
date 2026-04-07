#!/bin/bash

# OCI ARM Instance Launcher
# Attempts to launch an ARM always-free instance every 30 minutes
# Stops when successful and sends notification

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$SCRIPT_DIR/oci_arm_launcher.log"
STATUS_FILE="$SCRIPT_DIR/.oci_arm_status"
SUCCESS_FLAG="$SCRIPT_DIR/.oci_arm_success"

# Add common installation paths to PATH for cron environments
export PATH=$PATH:/home/ubuntu/bin:$HOME/bin:~/bin

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

# Detect Python binary early for notifications
if [ -f "$SCRIPT_DIR/venv/bin/python3" ]; then
    PYTHON_BIN="$SCRIPT_DIR/venv/bin/python3"
else
    PYTHON_BIN="python3"
    log "WARNING: venv not found, using system python3"
fi

# Install dependencies if needed
install_dependencies() {
    local needs_install=false

    # Check for Python3
    if ! command -v python3 &> /dev/null; then
        log "Python3 not found, will install..."
        needs_install=true
    fi

    # Check for curl
    if ! command -v curl &> /dev/null; then
        log "curl not found, will install..."
        needs_install=true
    fi

    if [ "$needs_install" = true ]; then
        log "Installing dependencies..."
        if command -v apt-get &> /dev/null; then
            sudo apt-get update
            sudo apt-get install -y python3 python3-pip curl
        elif command -v yum &> /dev/null; then
            sudo yum install -y python3 python3-pip curl
        else
            log "WARNING: Could not detect package manager. Please install python3 and curl manually."
        fi
    fi
}

# Install OCI CLI if needed
install_oci_cli() {
    if ! command -v oci &> /dev/null; then
        log "OCI CLI not found. Installing..."

        # Install dependencies first
        install_dependencies

        # Install OCI CLI
        bash -c "$(curl -L https://raw.githubusercontent.com/oracle/oci-cli/master/scripts/install/install.sh)" -- --accept-all-defaults

        # Add to PATH
        export PATH=$PATH:~/bin

        # Also add to bashrc/profile for persistence
        if [ -f ~/.bashrc ]; then
            if ! grep -q "~/bin" ~/.bashrc; then
                echo 'export PATH=$PATH:~/bin' >> ~/.bashrc
            fi
        fi

        if ! command -v oci &> /dev/null; then
            log "ERROR: Failed to install OCI CLI"
            return 1
        fi
        log "OCI CLI installed successfully"
    fi
    return 0
}

# Validate required environment variables first (before installing anything)
if [ -z "$COMPARTMENT_ID" ] || [ -z "$SUBNET_ID" ] || [ -z "$IMAGE_ID" ] || [ -z "$AD_NAME" ] || [ -z "$DISPLAY_NAME" ]; then
    log "OCI environment variables not configured, skipping launcher"
    echo "config_missing" > "$STATUS_FILE"
    echo "$(date +%s)" >> "$STATUS_FILE"
    exit 0
fi

# Install OCI CLI only if configuration is present
if ! install_oci_cli; then
    exit 1
fi

# Check OCI authentication configuration
log "Checking OCI authentication configuration..."

# Support custom OCI config path from .env or default locations
if [ -n "$OCI_CONFIG_FILE" ]; then
    OCI_CONFIG_ARG="--config-file $OCI_CONFIG_FILE"
elif [ -f "/home/ubuntu/.oci/config" ] && [ ! -f "$HOME/.oci/config" ]; then
    OCI_CONFIG_ARG="--config-file /home/ubuntu/.oci/config"
else
    OCI_CONFIG_ARG=""
fi

if ! oci $OCI_CONFIG_ARG iam region list &>/dev/null; then
    log "ERROR: OCI CLI authentication not configured"
    log "Please run 'oci setup config' or configure ~/.oci/config with your API key"
    echo "auth_not_configured" > "$STATUS_FILE"
    echo "$(date +%s)" >> "$STATUS_FILE"
    exit 0
fi
log "OCI authentication verified"

# Prepare SSH key - support both file and direct key from env
if [ -n "$SSH_AUTHORIZED_KEYS" ]; then
    # Use SSH key from environment variable via metadata
    log "Using SSH key from SSH_AUTHORIZED_KEYS environment variable"
    SSH_METADATA="{\"ssh_authorized_keys\": \"$SSH_AUTHORIZED_KEYS\"}"
    SSH_KEY_PARAM="--metadata"
    SSH_KEY_VALUE="$SSH_METADATA"
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

# Create unique log file for this run to avoid race conditions
LAUNCH_LOG="/tmp/oci_launch_log_$$.txt"

# Attempt to launch instance with --wait-for-state to ensure provisioning completes
oci compute instance launch \
    --availability-domain "$AD_NAME" \
    --compartment-id "$COMPARTMENT_ID" \
    --shape "VM.Standard.A1.Flex" \
    --shape-config '{"ocpus": 4, "memoryInGBs": 24}' \
    --subnet-id "$SUBNET_ID" \
    --image-id "$IMAGE_ID" \
    --display-name "$DISPLAY_NAME" \
    --assign-public-ip true \
    --wait-for-state RUNNING \
    $OCI_CONFIG_ARG \
    $SSH_KEY_PARAM "$SSH_KEY_VALUE" \
    2>&1 | tee "$LAUNCH_LOG"

EXIT_CODE=${PIPESTATUS[0]}

if [ $EXIT_CODE -eq 0 ]; then
    log "SUCCESS! ARM instance created and running."

    # Update status file and set success flag after instance is actually running
    echo "success" > "$STATUS_FILE"
    echo "$(date +%s)" >> "$STATUS_FILE"
    touch "$SUCCESS_FLAG"
    log "Success flag set, launcher will stop running"

    # Send notification using existing notify system with venv Python
    export ALERT_PAYLOAD="🎉 *OCI ARM Instance Created Successfully!*\n\nInstance: $DISPLAY_NAME\nShape: VM.Standard.A1.Flex (4 OCPUs, 24GB RAM)\n\nThe launcher has stopped running."
    if $PYTHON_BIN - <<EOF
import sys, os
sys.path.insert(0, "$SCRIPT_DIR")
from notify import notify
result = notify(os.environ["ALERT_PAYLOAD"])
sys.exit(0 if result else 1)
EOF
    then
        log "Notification sent successfully"
    else
        log "WARNING: Failed to send notification (instance was created successfully)"
    fi

    # Clean up log file on success
    rm -f "$LAUNCH_LOG"
    exit 0
else
    # Check error type
    SEND_ALERT=false
    if grep -q "Out of host capacity" "$LAUNCH_LOG"; then
        log "Out of capacity. Will retry later."
        echo "out_of_capacity" > "$STATUS_FILE"
    elif grep -q "LimitExceeded" "$LAUNCH_LOG"; then
        log "Limit exceeded. You may already have instances running."
        echo "limit_exceeded" > "$STATUS_FILE"
        ALERT_MSG="⚠️ *OCI ARM Launcher Alert*\n\nLimit exceeded for $DISPLAY_NAME. You may already have ARM instances running in this tenancy."
        SEND_ALERT=true
    else
        ERROR_DETAIL=$(tail -n 5 "$LAUNCH_LOG" | head -n 3)
        log "ERROR: Unknown error occurred. Check $LAUNCH_LOG"
        echo "error" > "$STATUS_FILE"
        ALERT_MSG="❌ *OCI ARM Launcher Error*\n\nAn unexpected error occurred while launching $DISPLAY_NAME:\n\n\`\`\`\n$ERROR_DETAIL\n\`\`\`"
        SEND_ALERT=true
        FATAL_ERROR=true
    fi
    echo "$(date +%s)" >> "$STATUS_FILE"

    # Send error notification if needed
    if [ "$SEND_ALERT" = true ]; then
        export ALERT_PAYLOAD="$ALERT_MSG"
        $PYTHON_BIN - <<EOF
import sys, os
sys.path.insert(0, "$SCRIPT_DIR")
from notify import notify
notify(os.environ["ALERT_PAYLOAD"])
EOF
    fi

    if [ "$FATAL_ERROR" = true ]; then
        exit 2
    else
        exit 1
    fi
fi
