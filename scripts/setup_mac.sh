#!/usr/bin/env bash
# One-time setup on macOS:   bash scripts/setup_mac.sh
# Creates .venv and installs everything. On Apple Silicon the chatbot engine is
# built with Metal (GPU) support; this needs the Xcode command line tools.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -c "import sys; assert sys.version_info >= (3, 10), 'Python 3.10+ is required'"
xcode-select -p >/dev/null 2>&1 || { echo "Installing Xcode command line tools (needed once)…"; xcode-select --install; exit 1; }
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
CMAKE_ARGS="-DGGML_METAL=on" .venv/bin/python -m pip install -r requirements.txt
echo
echo "Done. Start Airglide with:  bash scripts/run_mac.sh"
