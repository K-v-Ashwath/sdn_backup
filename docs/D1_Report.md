# Deliverable 1 — Architecture and Initial Implementation (15 marks)

Team: [fill names and SRNs] | Course: Computer Networks | Project: Distributed Backup System

## Problem and objectives (2)

Clients need reliable backup despite disrupted transfers or failed network paths. We implement TCP file replication to two servers and an SDN controller that selects paths and reroutes after link failure. Objectives: integrity, interrupted-transfer recovery, multiple clients/servers, repeatable tests and measured comparison.

## Architecture

Two clients h1/h2 -> s1; server A h3 -> s2; server B h4 -> s4. Four switch links form the cycle s1-s2-s4-s3-s1. POX programs Open vSwitch forwarding rules using OpenFlow 1.0. Data plane: TCP 9000. Control plane: TCP 6633. Application and controller are separate processes.

## TCP implementation (4)

See protocol.py, client.py and server.py. TCP is a byte stream, so explicit framing uses a 4-byte length and JSON metadata followed by binary bytes. Server uses one thread per connection and locks per file. Chunks are 64 KiB; each carries its offset and SHA-256. Server acknowledges only persisted bytes. Complete files require a whole-file hash check before atomic rename. Client retries with a bounded budget, obtains stored offset, and resumes.

## Mininet and SDN (4)

See topology.py and backup_controller.py. Four OVS switches connect to remote POX. Hosts have fixed addresses. Primary links have 5 ms delay; alternate links have 10 ms; each is limited to 10 Mbit/s. Controller computes minimum configured-cost routes and installs destination-IP flows. Proxy ARP resolves known hosts without flooding the cycle.

## Integration (3)

TCP packets traverse controller-installed switch flows. A switch link-state event changes the controller graph and forwarding rules; application transfer can continue through TCP retransmission or offset-based reconnect. This is network-event-driven integration; the application does not send a special SDN API request.

## Initial test and demo (2)

Run START_HERE sections 3–4. Save ping.json, client.json, integrity.json and normal-run screenshots. Expected acceptance: 0% ping loss, both replicas report success, both independent disk hashes match. Development-only socket tests are recorded in results/local_tests.txt. Mininet outcomes must be entered after rehearsal:

| Evidence | Actual result on team VM |
|---|---|
| Controller + four connected switches | [record] |
| All hosts reachable | [record] |
| Two successful TCP replicas | [record] |
| SHA-256 disk verification | [record] |

Do not submit bracket fields as completed experimental results.
