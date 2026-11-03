# Start here — tomorrow's live demo

This package implements the Distributed Backup System in your screenshot and maps to both rubric deliverables. You MUST rehearse it inside Ubuntu: Windows-only socket testing does not meet the Mininet requirement. No Mininet results have been invented. See results/local_tests.txt for tests actually run during development.

## 1. Put the folder in Ubuntu

Download and extract CN_Backup_Project.zip on Windows. Copy the extracted CN_Backup_Project folder into your Ubuntu VM's Home directory using VMware drag-and-drop/shared folders, or download the ZIP directly inside Ubuntu using your browser. Open Ubuntu Files > Home > CN_Backup_Project, right click the empty area > Open in Terminal. Every terminal below must be in this folder.

Recommended VM allocation: 2 CPU cores, 4 GB RAM, 15 GB free disk. Use VMware NAT with Connected and Connect at power on checked. Use the Ubuntu VM you already have if its package manager works. An Ubuntu 22.04/24.04 LTS VM is an alternative if your existing release's repositories fail; installing another VM takes additional time.

## 2. Check internet BEFORE installing

```bash
ip route
ping -c 3 8.8.8.8
getent hosts archive.ubuntu.com
sudo apt-get update
```

If `Network is unreachable`: in VMware check VM > Settings > Network Adapter > NAT and Connected. Inside Ubuntu turn wired networking off/on. Run `ip route` again: it needs a default route. If numeric ping works but `getent` fails, the problem is DNS. If apt fails with release/repository errors, record the exact error. Repeated downloads do not solve a disconnected VM. Do not change Ubuntu release names in sources manually.

## 3. Install once (internet needed)

```bash
cd ~/CN_Backup_Project
bash setup_ubuntu.sh
```

This installs Mininet, Open vSwitch, Git and Python, uses the bundled POX controller (downloads it only if missing), and copies our controller into POX. POX is an SDN controller; the rubric does not prescribe Ryu. These scripts use OpenFlow 1.0 consistently. Keep the pox folder after installation; the live demo then needs no internet. Do not run setup_ubuntu.sh during your presentation.

## 4. D1 / normal backup — two terminals

Terminal A:
```bash
cd ~/CN_Backup_Project
bash run_controller.sh dynamic
```
Leave it running. Open another Ubuntu terminal (Ctrl+Alt+T).

Terminal B:
```bash
cd ~/CN_Backup_Project
sudo mn -c
sudo python3 topology.py --scenario normal --tag normal
```

Expected: 0% dropped in pingAll; both endpoint results show `success: true`; results/normal/integrity.json has both server values true. Files stored as SHA-256.bin in results/normal/storage3 and storage4. JSON result is the evidence, not simply a command finishing.

## 5. D2 / link failure and automatic rerouting

Leave dynamic controller running in A. In B:
```bash
sudo python3 topology.py --scenario failure --tag dynamic_failure
```

The script sends an 8 MiB file, disables s1-s2 two seconds later, then waits for transfer completion. Observe LINK and ROUTES lines in A. The alternate route to server A is s1-s3-s4-s2. Expect success in client.json and server3 true in integrity.json. Server4 false is expected here: this experiment targets only server A. A brief interruption may be absorbed by TCP retransmission without an application reconnect, so retries can be zero.

## 6. Static baseline with the SAME failure

Stop controller A with Ctrl+C, then in A:
```bash
bash run_controller.sh static
```
In B:
```bash
sudo python3 topology.py --scenario failure --tag static_failure
```

Static mode keeps its initial routes when the link fails. It should fail within the finite retry budget (roughly under a minute), producing success false; do not call that a bug. This is the baseline showing why dynamic rerouting matters. Compare actual JSON outputs.

## 7. Restart recovery and concurrent clients

Stop static controller in A and start dynamic again:
```bash
bash run_controller.sh dynamic
```
In B run sequentially:
```bash
sudo python3 topology.py --scenario server-recovery --tag server_recovery
sudo python3 topology.py --scenario concurrent --tag concurrent
sudo python3 summarize.py
```

Recovery kills server A mid-transfer, restarts it after three seconds, and checks that the client resumes. Concurrent uses h1 to A and h2 to B at the same time. Read both client.json and client2.json. Server restart recovery does not claim automatic failover to another server.

Open results/comparison.csv with LibreOffice Calc. Repeat experiments with distinct tags (normal_r2, dynamic_failure_r2, etc.) if time permits; discuss variability, not an unmeasured universal speedup.

## 8. Interactive commands, if ma'am asks

With dynamic controller still running:
```bash
sudo python3 topology.py --scenario cli --tag interactive
```
At the `mininet>` prompt (do NOT type the prompt text):
```text
nodes
net
pingall
h1 python3 client.py results/interactive/sample.bin --json results/interactive/manual.json
sh ovs-ofctl -O OpenFlow10 dump-flows s1
link s1 s2 down
h1 ping -c 3 10.0.0.3
link s1 s2 up
exit
```

Show packet traces optionally: `sudo tcpdump -i s1-eth3 -nn tcp port 9000` from a third Ubuntu terminal while traffic runs. tcpdump is optional and may need installation.

## 9. What to keep for submission

Fill team names/SRNs in docs/D1_Report.md and docs/D2_Report.md. Add REAL screenshots of normal success, failure log, alternate route, static failure, restart success, and comparison.csv. Results are generated on your laptop; they are not supplied as made-up proof. Use docs/Presentation_and_Viva.md to explain the implementation. Push code and documentation to your team's GitHub repository, as the rubric requires.

GitHub via website: create a repository > Add file > Upload files. Upload source files and docs (not the ZIP alone, not pox, not stored backups). Or use the Git commands in README.md. Do not publish personal backup contents.

## Problems

- `No module named mininet`: use `sudo python3`, ensure apt install completed; avoid a Python virtual environment here.
- Controller not connected: check Terminal A errors, `ss -ltn | grep 6633`, then run `sudo mn -c` after exiting old Mininet.
- Address already in use: close the previous controller; do not start two controllers.
- pingAll fails: confirm current controller was copied by run_controller.sh and all four switches connected. Do not proceed with performance claims until connectivity works.
- Permission denied in results: created by sudo. Run `sudo chown -R "$USER":"$USER" results` after stopping Mininet.
- GitHub clone fails: fix internet first. Alternatively download POX ZIP from https://github.com/noxrepo/pox in a browser, extract and rename that folder to pox beside setup_ubuntu.sh, then rerun setup.
- Cleanup after a crash: Ctrl+C, then `sudo mn -c`. Reopen the two terminals and retry.

## Windows quick confidence test (optional)

In a Windows terminal in the extracted folder, run `py local_demo.py` (or `python local_demo.py`). This proves the Python TCP application works. It is NOT a substitute for Mininet + SDN.
