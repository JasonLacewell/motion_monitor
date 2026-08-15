#!/usr/bin/env bash
#
# One-time setup for Motion Monitor.
#
#   1. Creates a virtual environment (./venv) if it doesn't exist.
#   2. Installs dependencies from requirements.txt.
#   3. Creates config/config.json from the example template, if missing.
#
# Usage:
#   ./setup.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Motion Monitor setup ==="
echo

# 1. Virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment (./venv)..."
    python3 -m venv venv
else
    echo "Virtual environment already exists (./venv) - skipping creation."
fi

# 2. Install dependencies into the venv
echo "Installing dependencies from requirements.txt..."
./venv/bin/pip install --upgrade pip --quiet
./venv/bin/pip install -r requirements.txt --quiet

# 3. Local config file
if [ ! -f "config/config.json" ]; then
    echo "Creating config/config.json from the example template..."
    cp config/config.example.json config/config.json
    echo
    echo ">>> IMPORTANT: edit config/config.json and fill in your"
    echo ">>> Telegram bot token and chat id before running the app."
else
    echo "config/config.json already exists - leaving it as is."
fi

# 4. ffmpeg check (used for video+audio recording, installed separately via Homebrew)
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo
    echo ">>> NOTE: ffmpeg was not found on your system."
    echo ">>> Video+audio recording needs it. Install with:"
    echo ">>>   brew install ffmpeg"
fi

echo
echo "Setup complete."
echo "Next steps:"
echo "  1. Edit config/config.json with your Telegram bot token and chat id."
echo "  2. Run ./run.sh to start Motion Monitor."
