#!/usr/bin/env bash
# Start Airglide from source on macOS (run scripts/setup_mac.sh once first).
cd "$(dirname "$0")/.."
[ -x .venv/bin/python ] || { echo "Run setup first: bash scripts/setup_mac.sh"; exit 1; }
exec .venv/bin/python main.py
