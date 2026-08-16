#!/usr/bin/env bash
#
# Starts Motion Monitor using the project's virtual environment.
# No need to activate the venv yourself - this script handles it.
#
# Usage:
#   ./run.sh
#   ./run.sh --calibrate    # live threshold tuning, nothing saved/sent
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
if [ ! -d "venv" ]; then
    echo "No virtual environment found."
    echo "Run ./setup.sh first."
    exit 1
fi
if [ ! -f "config/config.json" ]; then
    echo "No config/config.json found."
    echo "Run ./setup.sh first, then edit config/config.json."
    exit 1
fi
./venv/bin/python3 src/motion_monitor.py "$@"
