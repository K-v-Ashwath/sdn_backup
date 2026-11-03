# Presentation script and viva

## Opening (30 seconds)

“Our project is a distributed backup system over an SDN-controlled network. Two clients can send files through TCP to two backup servers. We divide files into chunks, verify integrity with SHA-256, and resume incomplete transfers. The controller chooses paths and reroutes when a network link fails.”

## Show architecture (30 seconds)

“Mininet creates four virtual switches and four hosts. h1 and h2 are clients; h3 and h4 are servers. POX controls the Open vSwitch forwarding rules through OpenFlow. Data transfers use TCP port 9000; controller communication uses port 6633. Two alternative network paths allow recovery.”

## D1 live demo (one minute)

Run the normal scenario. Show both successful results and integrity.json. Say: “Each server acknowledges chunks after writing them. The final result is successful only after the full-file hash matches. These two stored files are complete replicas.”

## D2 live demo (two minutes)

Run failure with dynamic controller. Point to the failed link and updated controller route. Say: “The direct s1-s2 link has failed. The controller now sends traffic through s1-s3-s4-s2. TCP may retransmit during the change. If the connection times out, our client reconnects and asks for the saved offset.”

Show the rehearsed static baseline result and comparison.csv. If time allows, run it live. Explain: “Both versions use the same application. Static routing does not update after failure. Dynamic routing can complete through the alternate path.” Only say it completed after seeing success=true.

## Server recovery

“Here we restart a server during transfer. Previously acknowledged chunks remain on disk. The client resumes instead of retransmitting the entire file. We do not claim automatic failover to another server.”

## Likely questions

- Why TCP? Reliable ordered byte transport, with congestion control and retransmissions.
- Why framing? TCP has no application message boundaries; one recv may return only part of a message.
- Why checksums if TCP is reliable? We verify application chunks and stored complete-file content, beyond successful byte transport.
- What is SHA-256? A cryptographic digest producing a 256-bit content fingerprint; it is not encryption.
- Why chunks? Bounded messages, progress acknowledgments and resumable partial transfers.
- How does resume avoid duplicates? Server reports committed byte offset, even if the client missed the last ACK.
- What is SDN? Software in a controller programs forwarding behavior in switches.
- Controller versus switch? Controller selects routes; switches forward matching packets.
- What is OpenFlow? A protocol used by the controller to install rules and receive switch events.
- Why POX instead of Ryu? The rubric requires an SDN controller without naming one; POX gives Python 3/OpenFlow 1.0 support for this implementation.
- How is a path selected? Dijkstra minimizes configured cost over available edges. Costs reflect configured delay; live load is not measured.
- How is failure detected? Switch PortStatus reports link-down; controller removes that edge from routing.
- Does the client know the network route? No. It uses the same server IP while SDN changes forwarding.
- Why proxy ARP? Hosts need destination MAC addresses; controlled replies avoid flooding loops in this redundant topology.
- Concurrency? Thread-per-connection server and one lock per file prevent overlapping same-file writes. Two clients can transfer different files concurrently.
- Does one failed server automatically redirect backup? No; retries resume on that endpoint. Replicas on other servers are independent copies.
- What is the baseline? Identical initial routes and application with link-event rerouting disabled.
- Throughput formula? Payload bits divided by elapsed seconds; report Mbit/s.
- Recovery-time measurement? Max ACK gap is a proxy including pacing/RTT; exact event-to-recovery requires aligned packet/event timestamps.
- What did you personally do? State your actual contribution: installation, experiments, testing, implementation review or documentation. Do not claim work you cannot explain.

## Before leaving for college

Run normal and failure at least once. Keep the working VM suspended or shut it down cleanly. Keep ZIP and code locally, results/screenshots, GitHub URL, charger, and controller already installed. No internet should be necessary for the rehearsed demo.
