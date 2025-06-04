#!/bin/bash
source venv/bin/activate

# Export .env variables
export $(grep -v '^#' .env | xargs)

# Now run the script
python monitor.py
