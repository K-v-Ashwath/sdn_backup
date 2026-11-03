# Vault Web UI

Animated browser dashboard for the existing CN Backup Project. It uses the project's real `client.py`, `server.py`, POX controller, and Mininet topology; it does not replace the TCP protocol.

## Install and run (Ubuntu VM)

From the project root:

```bash
sudo apt-get update
sudo apt-get install -y python3-flask mininet openvswitch-switch
sudo systemctl start openvswitch-switch
sudo mn -c
sudo python3 webui/app.py
```

Open `http://127.0.0.1:8080` inside the Ubuntu VM. If browsing from the host computer, use the VM's IP address (find it with `hostname -I`): `http://VM_IP:8080`.

The app must run as root because Mininet/OVS need root privileges. It starts POX itself, builds the same four-switch/four-host topology used by `topology.py`, checks connectivity, and starts Server A/B. Use **Start network** before uploading. Choose dynamic or static mode before starting. Upload supports binary files, including videos; no transcoding occurs. The TCP server's current per-file size ceiling is 1 GiB.

The dashboard reports ICMP round-trip latency from h1 to Server A, installed non-controller flow counts, server state and stored files, transfer outcome and throughput reported by the existing client, and a timestamped event stream. Latency is a periodic on-demand ping measurement, not one-way delay. The animated topology and packet dots are visual indicators, not packet-level visualization.

Use **Stop network** before starting another topology from a terminal. The UI owns its POX and Mininet processes while running. On an unclean shutdown, run `sudo mn -c` before relaunching. Logs and data are stored under `results/webui/`; browser uploads are stored under `webui/uploads/`.

## Notes / limitations

- This is a lab control panel, not a production file-sharing service. It has no login/authentication or TLS. Do not expose port 8080 to an untrusted network.
- Files are saved on the VM and replicated to the selected backup node(s). The UI does not stream video playback.
- The progress animation indicates an active transfer; exact byte-level progress is not currently emitted by the TCP client.
- The dashboard's flow counts are read from OVS and may be zero briefly while flows are being learned/installed.

## Network fault controls

When the Mininet network is running, the dashboard exposes controls for each switch (`s1`–`s4`) and each inter-switch link. **Take down** stops the selected Mininet OVS switch while retaining its interfaces; **Bring up** restarts it with the configured controller. Link controls administratively disable/enable both ends of the selected inter-switch link. These are real Mininet actions, not visual-only toggles. Use them for controlled failure/recovery experiments; an interrupted transfer may fail if its retry/resume window is exceeded.

## Transfer diagnostics and live topology

The dashboard exposes per-transfer diagnostics from the TCP client. The client emits a structured `PROGRESS` record after each acknowledged 64 KiB chunk; the web API reads the latest record from that transfer's log and displays acknowledged chunk count, total chunks, bytes acknowledged, retry count, and percentage. The route shown for a transfer is a snapshot of the POX controller's published route table at the time the transfer was started. It is a route snapshot, not packet-by-packet path inference.

The topology animation samples Linux interface RX/TX byte counters on the Mininet switch ports. It establishes a baseline on the first poll and animates only when a later sample shows a counter increase. A direction-aware SVG animation moves particles along the corresponding edge. No particles should appear while counters remain unchanged. This telemetry is sampled every 2.5 seconds by the dashboard.

### Load-aware routing telemetry

The dashboard now shows per-link utilisation and dynamic cost from POX's
OpenFlow port-statistics polling. Dynamic mode uses measured byte-counter
rates plus the topology's configured TCLink delay in its Dijkstra cost.
Static mode retains fixed base costs. The delay shown is configured propagation
delay, not a live RTT measurement.

## Reliability fixes (latest version)

- **Re-routing no longer stalls a transfer.** The server closes a dead connection as soon as the same file reconnects (previously the new connection waited ~20 s for the old one to time out), enables TCP keep-alive, and the client does not count attempts that made progress against its retry budget.
- **One unreachable server no longer blocks the other.** The client sends to all selected servers in parallel. A transfer can finish as **PARTIAL** (stored on one server, failed on the other); each server has its own progress card showing *Sending*, *Reconnecting*, *Stored and verified* or *Failed*.
- **No blank window when routes change.** The controller replaces flow rules in place instead of deleting the table first, and load-aware re-routing has hysteresis (new path must be ≥40 % cheaper and 20 s since the last change) so a busy path does not bounce traffic back and forth. A failed link or switch is still abandoned immediately.
- UI/back-end fixes: status polling no longer blocks on Mininet (background sampler + lock), single polling loop, no repeated error toasts, upload button/progress no longer flicker or allow double submit, same file can be chosen twice, traffic particles on the h3/h4 links point the right way, stopping while starting cleans up, stale `routes.json` is cleared on start, safer upload file names, JSON errors for oversized uploads.
