#!/bin/bash

# Get directory of this script (i.e., repo root)
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load .env from the same directory
set -a
source "$REPO_DIR/.env"
set +a

# Check if the service is running
if ! systemctl is-active --quiet page-watcher; then
  curl -s -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
    -d chat_id="${TG_CHAT_ID}" \
    -d text="❗️ Page Watcher is NOT running on $(hostname)"
fi
