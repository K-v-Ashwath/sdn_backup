# Deliverable 2 — Complete System and Evaluation (25 marks)

Team: [fill names and SRNs]

## Complete application functionality (4)

Two full backup replicas, binary-safe TCP transport, 64 KiB chunks, chunk and final checksum verification, durable partial files, reconnect/resume, threaded servers, concurrent client experiment, finite timeouts and retries. Resume is per destination server. Replication is sequential in the default client; the concurrent scenario uses separate client processes. Backup storage is implemented; restore/download and automatic server failover are outside scope.

## Dynamic SDN functionality (6)

POX reacts to OpenFlow PortStatus, marks failed edge endpoints unavailable, reruns Dijkstra over configured link costs, and replaces forwarding entries. Primary A route: s1-s2. After failure: s1-s3-s4-s2. On link restoration it can return to the lower-cost route. Static mode keeps existing routes during failure, providing a baseline. Proxy ARP prevents cyclic broadcast storms. This is link-state adaptive routing, not measured load balancing.

## Challenging scenarios and robustness (4)

1. Disable s1-s2 two seconds into an 8 MiB transfer; dynamic controller should reroute.
2. Terminate server A mid-transfer and restart after three seconds; durable partial file should permit client resume.
3. Two simultaneous clients target different backup servers.
4. Negative application tests reject corrupt chunk and final hash mismatch.

Run the exact commands in START_HERE. Capture controller logs, client logs, result JSON, independent integrity.json and screenshots. TCP may recover from a short outage without application retries; explain that honestly.

## Performance evaluation and comparison (5)

Normal dynamic, failed-link dynamic and failed-link static use the same topology, 8 MiB payload size, rate limits, client timeout, chunk size and artificial 15 ms/chunk pause. Fresh random content prevents deduplication from eliminating transfer work. Pausing is identical across experiments and must be disclosed when interpreting throughput. Server-recovery and concurrent are additional robustness experiments.

Measured transfer time: monotonic time from first connect attempt to verified completion, including retries/backoff. Goodput (Mbit/s): file_size_bytes * 8 / elapsed_seconds / 1e6. Also record success, retries, resumed offset and maximum interval between chunk acknowledgments. The maximum ACK gap is an interruption proxy; it includes normal RTT and deliberate pacing, and is NOT exact controller recovery latency. event_epoch records failure injection for timestamped external capture if precise timing is required. A failed static run has no completed-transfer throughput: report N/A, not a claimed measured zero. Compare success and time-to-failure separately.

Run each condition at least three times with unique tags if feasible; summarize mean/range for successful runs and report failure counts separately. Do not compare localhost test throughput to Mininet throughput.

| Condition | Success count / trials | Time (s) | Goodput (Mbit/s) | Retries | Max ACK gap (s) |
|---|---|---|---|---|---|
| Normal dynamic | [measure] | [measure] | [measure] | [measure] | [measure] |
| Failure dynamic | [measure] | [measure] | [measure] | [measure] | [measure] |
| Failure static | [measure] | [measure] | N/A if failed | [measure] | [measure] |
| Server restart | [measure] | [measure] | [measure] | [measure] | [measure] |

Generate results/comparison.csv using summarize.py. Explain any failures; do not replace missing measurements with expected numbers.

## Documentation, final demo and viva (6)

Use README, START_HERE, source files, results and Presentation_and_Viva. Publish the final code and completed documentation to your GitHub repository; insert its actual URL here: [team repository]. Include Ubuntu version, Python version, Mininet version and recorded POX commit. No GitHub repository has been created by this package.

## Limitations

Static known topology and host table; no authentication/TLS, real-time congestion sensing, distributed metadata service, automatic cross-server failover or backup restore operation. Flow replacement is not atomic across switches; brief packet loss may occur and TCP recovers. Routes adapt to link events, not arbitrary switch process failure. Rehearsal and Mininet measurements are required before claiming full integration validation.
