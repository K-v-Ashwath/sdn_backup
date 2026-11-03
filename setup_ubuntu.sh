#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
sudo apt-get update
sudo apt-get install -y mininet openvswitch-switch python3 git
sudo systemctl start openvswitch-switch
if [ ! -f pox/pox.py ]; then git clone https://github.com/noxrepo/pox.git pox; fi
cp backup_controller.py pox/ext/backup_controller.py
if [ -f pox/BUNDLED_COMMIT.txt ]; then cp pox/BUNDLED_COMMIT.txt results/pox_version.txt; else git -C pox rev-parse HEAD > results/pox_version.txt; fi
sudo mn --version
