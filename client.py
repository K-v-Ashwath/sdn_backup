import argparse, hashlib, json, socket, threading, time
from pathlib import Path
from protocol import send, receive

CHUNK = 65536
_PRINT = threading.Lock()


def progress(**fields):
    """One structured line per event; the web UI reads the newest line per endpoint."""
    with _PRINT:
        print('PROGRESS ' + json.dumps(fields), flush=True)


def file_sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def backup(path, endpoint, attempts=30, pause=0, timeout=3, fid=None, flip_bit=False):
    """Send `path` to one server, reconnecting and resuming after failures.

    `attempts` is the number of *consecutive failures without progress* that are
    tolerated: an attempt that moved the acknowledged offset forward does not use up the
    budget, so a transfer that is re-routed several times is not abandoned.
    """
    host, port = endpoint.rsplit(':', 1)
    fid = fid or file_sha256(path)
    size = path.stat().st_size
    start = time.monotonic(); retries = 0; resumed = 0; acked = 0; gaps = []; last_ack = None
    total_chunks = (size + CHUNK - 1) // CHUNK; chunk_index = 0; failures = 0; last_error = ''; bit_flip_pending = bool(flip_bit); bit_flip_injected = False; checksum_failures = 0

    def report(state, **extra):
        progress(endpoint=endpoint, state=state, chunk=chunk_index, total_chunks=total_chunks, chunk_size=CHUNK,
                 acknowledged_bytes=acked, total_bytes=size, percent=round((acked / size * 100) if size else 100, 2),
                 retries=retries, resumed_offset=resumed, failures=failures, max_failures=attempts, checksum_failures=checksum_failures, bit_flip_injected=bit_flip_injected,
                 last_ack_age=round(time.monotonic() - last_ack, 1) if last_ack else None, **extra)

    report('connecting')
    while failures < attempts:
        before = acked
        try:
            with socket.create_connection((host, int(port)), timeout=timeout) as sock:
                sock.settimeout(timeout)
                send(sock, {'file_id': fid, 'size': size})
                reply, _ = receive(sock)
                offset = reply['offset']; resumed = max(resumed, offset); acked = offset
                chunk_index = (offset + CHUNK - 1) // CHUNK
                print(endpoint, 'starting/resuming at byte', offset, flush=True)
                if not reply.get('complete'):
                    with path.open('rb') as f:
                        f.seek(offset)
                        while offset < size:
                            data = f.read(CHUNK)
                            original_digest = hashlib.sha256(data).hexdigest()
                            wire_data = data
                            if bit_flip_pending and data:
                                damaged = bytearray(data); damaged[0] ^= 0x01; wire_data = bytes(damaged); bit_flip_pending = False; bit_flip_injected = True
                                print('FAULT INJECTION: flipped one bit in the first transmitted chunk; receiver should reject its SHA-256 checksum.', flush=True)
                            send(sock, {'offset': offset, 'sha256': original_digest}, wire_data)
                            reply, _ = receive(sock)
                            if reply.get('error'):
                                if 'checksum' in reply['error'].lower():
                                    checksum_failures += 1
                                    report('checksum_failure', error=reply['error'])
                                raise ValueError(str(reply))
                            if reply.get('ack') != offset + len(data):
                                raise ValueError(str(reply))
                            offset = reply['ack']; acked = offset; chunk_index += 1
                            now = time.monotonic()
                            if last_ack is not None: gaps.append(now - last_ack)
                            last_ack = now
                            report('sending')
                            if pause: time.sleep(pause)
                    reply, _ = receive(sock)
                    if not reply.get('verified') or reply.get('sha256') != fid:
                        raise ValueError(str(reply))
                elapsed = time.monotonic() - start
                acked = size
                report('done')
                return dict(endpoint=endpoint, success=True, size=size, sha256=fid, seconds=elapsed,
                            throughput_mbps=size * 8 / max(elapsed, 1e-9) / 1e6, retries=retries, resumed_offset=resumed,
                            bit_flip_injected=bit_flip_injected, checksum_failures=checksum_failures, checksum_rejected=checksum_failures > 0,
                            max_ack_gap_seconds=max(gaps, default=0), chunk_size=CHUNK, chunks=total_chunks)
        except (OSError, ConnectionError, ValueError, KeyError, TypeError) as exc:
            retries += 1
            failures = 0 if acked > before else failures + 1
            last_error = str(exc) or exc.__class__.__name__
            print(endpoint, 'retry', retries, last_error, flush=True)
            report('retrying', error=last_error)
            if failures < attempts:
                time.sleep(min(2.0, 0.5 * max(1, failures)))
    report('failed', error=last_error)
    return dict(endpoint=endpoint, success=False, size=size, bytes_acknowledged=acked, seconds=time.monotonic() - start,
                retries=retries, error=last_error or 'unreachable', bit_flip_injected=bit_flip_injected,
                checksum_failures=checksum_failures, checksum_rejected=checksum_failures > 0)


def backup_all(path, endpoints, attempts=30, pause=0, timeout=3, flip_bit=False):
    """Send to every endpoint at the same time: one unreachable server must not delay or block the others."""
    fid = file_sha256(path)
    results = [None] * len(endpoints)

    def run(i, endpoint):
        try:
            results[i] = backup(path, endpoint, attempts, pause, timeout, fid, flip_bit)
        except Exception as exc:  # never lose a server's result because of an unexpected error
            results[i] = dict(endpoint=endpoint, success=False, size=path.stat().st_size, error=repr(exc), retries=0, seconds=0)

    threads = [threading.Thread(target=run, args=(i, e), daemon=True) for i, e in enumerate(endpoints)]
    for t in threads: t.start()
    for t in threads: t.join()
    return results


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('file', type=Path); p.add_argument('--servers', nargs='+', default=['10.0.0.3:9000', '10.0.0.4:9000'])
    p.add_argument('--attempts', type=int, default=30); p.add_argument('--pause', type=float, default=0); p.add_argument('--timeout', type=float, default=3)
    p.add_argument('--json', default='results/client.json'); p.add_argument('--flip-bit', action='store_true', help='corrupt one bit in the first transmitted chunk to demonstrate receiver-side SHA-256 rejection')
    a = p.parse_args(); results = backup_all(a.file, a.servers, a.attempts, a.pause, a.timeout, a.flip_bit)
    out = Path(a.json); out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(results, indent=2)); print(json.dumps(results, indent=2))
    ok = sum(1 for r in results if r['success'])
    # 0 = every server stored the file, 2 = only some did, 1 = none did
    raise SystemExit(0 if ok == len(results) else 2 if ok else 1)
