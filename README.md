# Distributed Backup System over SDN

Python TCP client/server, chunk-level and whole-file SHA-256 validation, durable partial transfers, two backup servers, concurrent clients, POX OpenFlow routing and failure recovery in Mininet.

Read **START_HERE.md** first. Then see docs/D1_Report.md, docs/D2_Report.md and docs/Presentation_and_Viva.md.

## Architecture

Clients h1 (10.0.0.1) and h2 (.2) attach to s1. Server A h3 (.3) attaches to s2. Server B h4 (.4) attaches to s4. Switch links: s1-s2, s1-s3, s2-s4, s3-s4. POX controls all four switches over TCP 6633. Backup application listens on TCP 9000. All hosts have fixed IP/MAC addresses.

Configured path costs: s1-s2=1, s2-s4=1, s1-s3=2, s3-s4=2. Dijkstra chooses the available minimum-cost route; these reflect the configured 5/10 ms link delays. No measured congestion-based optimization is claimed. On port link-state events, dynamic mode updates the graph and replaces destination forwarding rules. Static mode ignores these changes after initial routing. Controller handles ARP with known-host proxy replies, preventing broadcast loops in the redundant topology.

## Files

- protocol.py: exact reads, bounded length-prefixed JSON and binary payloads.
- server.py: threaded TCP listeners, per-file locks, partial files, acknowledgments, SHA-256 and atomic completion rename.
- client.py: bounded reconnects, saved-offset resume, two sequential full replicas by default.
- backup_controller.py: POX component, Dijkstra, proxy ARP, PortStatus recovery.
- topology.py: four switches/four hosts, normal/failure/restart/concurrent/interactive runs.
- summarize.py: measured results to CSV, no synthetic values.
- tests/test_application.py: socket integration tests.
- local_demo.py: Windows/Linux socket-only smoke demo.

## Protocol

Frame = 4-byte network-order JSON length + JSON bytes + binary payload of header payload_length. First frame carries file_id=SHA256 and size. Server responds with durable offset. Client sends 64 KiB chunks with byte offset and SHA256. Server checks, writes, flushes, fsyncs, and ACKs the new offset. After final chunk ACK, a separate final verification frame confirms whole-file hash and atomic rename. Disconnection leaves .part intact. A later session queries its offset; a missing ACK is harmless because the server reports committed bytes. Fully stored files return complete=true after verifying their hash.

File IDs eliminate path traversal through submitted names. Header and payload lengths are bounded, with a 1 GiB declared file limit. This is a trusted lab protocol: no authentication, encryption, production quota, automatic data retrieval or cross-server failover. Final digest currently reads a file into memory, so use small demo files. The per-file lock serializes same-file writes; different files and clients can be served concurrently.

## Verification status

Development environment: socket integration suite and local replicas tested. Real Mininet/OVS not installed here; topology and controller require local rehearsal. See results/local_tests.txt and results/controller_checks.txt (if present). The package is an implementation plus reproducible experiments, not a claim of already collected Mininet results.

## GitHub submission

Create an empty GitHub repository, then from this folder (replace URL with your actual repo):
```bash
git init
git add .
git commit -m "Implement TCP distributed backup with SDN recovery"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

Record real results in the reports before submission. Preserve POX commit from results/pox_version.txt to document your tested dependency version. POX upstream: https://github.com/noxrepo/pox; Mininet: https://mininet.org/.


## Animated browser dashboard

A browser-based control panel is included in `webui/`. It starts/stops the POX + Mininet network, starts both TCP backup servers, accepts binary file uploads (including videos), sends uploads through the existing TCP client, and displays measured ICMP RTT, OVS flow counts, server storage, transfer outcomes/throughput, and events.

On Ubuntu, install Flask and ensure Mininet/OVS are installed, then run:

```bash
sudo apt-get install -y python3-flask mininet openvswitch-switch
sudo systemctl start openvswitch-switch
sudo mn -c
sudo python3 webui/app.py
```

Open `http://127.0.0.1:8080` in the VM browser. Full instructions and limitations: `webui/README.md`. Run the web app as root because it manages Mininet/OVS. Do not expose the unauthenticated lab dashboard to untrusted networks.

## Load-aware routing (dynamic POX mode)

In `dynamic` mode the POX controller requests OpenFlow 1.0 port statistics every
2 seconds. It calculates each inter-switch link's utilisation from byte-counter
deltas and the configured 10 Mbps link capacity. The controller then uses
Dijkstra with this cost:

`cost = base_cost + configured_delay_ms / 5 + 12 * utilisation_fraction^2`

The configured delay is the `TCLink` propagation delay from `topology.py`; it
is not a live measured RTT. Utilisation is live and comes from OpenFlow port
statistics. If the selected path changes, POX removes stale destination flows
and installs the new path. A path change is only triggered when the selected
switch sequence changes, which avoids needless flow churn. `static` mode keeps
the original fixed base costs and does not reroute based on load, making it a
useful baseline for comparison.

The dashboard's **Live link costs & utilisation** panel displays each link's
measured utilisation, configured delay, and current dynamic cost. Allow at
least two statistics polling intervals after starting the network before
expecting meaningful utilisation values; idle links correctly remain near 0%.
