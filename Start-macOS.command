#!/bin/bash
set -eu
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
  ./Setup-macOS.command
fi
.venv/bin/python app.py
