#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ $EUID -ne 0 ]]; then echo "Run: sudo ./webui/start_webui.sh"; exit 1; fi
exec python3 webui/app.py
