#!/bin/bash

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
set -a
source "$REPO_DIR/.env"
set +a

# Check if the Page Watcher Python process is running
if ! pgrep -f "page-watcher.*python" > /dev/null; then
  curl -s -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
    -d chat_id="${TG_CHAT_ID}" \
    -d text="❗️ Page Watcher process is NOT running on $(hostname)"
else
  curl -s -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
    -d chat_id="${TG_CHAT_ID}" \
    -d text="✅ Page Watcher service restarted and is running on $(hostname)"
fi
