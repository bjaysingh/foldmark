#!/bin/bash
set -eu
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 was not found. Install Python 3.10 or newer from https://www.python.org/downloads/macos/"
  read -r -p "Press Return to close..."
  exit 1
fi

if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)'; then
  echo "Python 3.10 or newer is required. Download it from https://www.python.org/downloads/macos/"
  read -r -p "Press Return to close..."
  exit 1
fi

echo "Creating the private app environment..."
python3 -m venv .venv
echo "Installing Microsoft MarkItDown and desktop components..."
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
echo
echo "Setup complete. Double-click Start-macOS.command to use the app."
read -r -p "Press Return to close..."
