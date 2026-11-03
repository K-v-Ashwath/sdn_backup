#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mode="${1:-dynamic}"
cp backup_controller.py pox/ext/backup_controller.py
mkdir -p results
python3 -u pox/pox.py openflow.of_01 --port=6633 backup_controller --mode="$mode" 2>&1 | tee "results/controller_${mode}.log"
