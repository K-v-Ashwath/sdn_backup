#!/usr/bin/env bash
# One-command launcher for CN_Backup_Project (Ubuntu/Mininet VM).
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [[ ! -f "$ROOT/webui/app.py" || ! -f "$ROOT/pox/pox.py" ]]; then
  echo "ERROR: Run this script from inside the extracted CN_Backup_Project folder."
  exit 1
fi

if [[ $EUID -ne 0 ]]; then
  echo "Requesting sudo privileges..."
  exec sudo -E bash "$0" "$@"
fi

log_step() { echo; echo "============================================================"; echo "$1"; echo "============================================================"; }

log_step "1/6  Installing required Ubuntu packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-flask mininet openvswitch-switch iproute2 iputils-ping

log_step "2/6  Starting Open vSwitch and cleaning old Mininet state"
systemctl enable --now openvswitch-switch
mn -c

log_step "3/6  Checking Python syntax"
python3 -m py_compile client.py server.py protocol.py backup_controller.py webui/app.py

log_step "4/6  Running TCP application tests"
python3 -m unittest discover -s tests -v

log_step "5/6  Running POX controller logic tests"
PYTHONPATH="$ROOT/pox" python3 tests/check_controller.py

log_step "6/6  Starting the web dashboard"
echo "The dashboard will start POX, Mininet and both backup servers when you click Start Network."
echo "Open http://127.0.0.1:8080 inside Ubuntu."
echo "To access from your host machine, use the VM IP shown below with port 8080."
hostname -I || true
echo
echo "Keep this terminal open. Press Ctrl+C to stop the dashboard."
exec python3 -u webui/app.py
