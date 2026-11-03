import argparse, hashlib, json, os, socket, socketserver, threading
from pathlib import Path
from protocol import send, receive
LOCKS = {}
ACTIVE = {}      # file_id -> socket of the connection currently serving that file
GUARD = threading.Lock()
LOCK_WAIT = 15   # seconds a new connection waits for a stale one to release the file

def digest(data):
    return hashlib.sha256(data).hexdigest()

def file_digest(path):
    # Stream the file: a 1 GiB backup must not need 1 GiB of RAM to verify.
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()

def keepalive(sock):
    # Detect a peer that vanished (path failure) in ~10 s instead of hanging for minutes.
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 4)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 2)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
    except (OSError, AttributeError):
        pass

class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(15)
        keepalive(self.request)
        fid = None
        locked = False
        try:
            meta, _ = receive(self.request)
            fid = meta['file_id']
            size = meta['size']
            if not isinstance(fid, str) or len(fid) != 64 or any(c not in '0123456789abcdef' for c in fid) or not isinstance(size, int) or not 0 <= size <= 1024**3:
                fid = None
                raise ValueError('Invalid file metadata (limit 1 GiB)')
            with GUARD:
                lock = LOCKS.setdefault(fid, threading.Lock())
                stale = ACTIVE.get(fid)
                ACTIVE[fid] = self.request
            # A client that reconnects after a path failure leaves a half-dead connection
            # behind. That old handler still owns the file lock, so close it right away
            # instead of making the new connection wait for the old one to time out.
            if stale is not None:
                try:
                    stale.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            locked = lock.acquire(timeout=LOCK_WAIT)
            if not locked:
                raise ConnectionError('previous connection did not release the file in time')
            self.transfer(fid, size)
        except (OSError, ValueError, KeyError, ConnectionError, TypeError) as exc:
            print('Connection ended:', exc, flush=True)
        finally:
            if locked:
                lock.release()
            if fid is not None:
                with GUARD:
                    if ACTIVE.get(fid) is self.request:
                        del ACTIVE[fid]

    def transfer(self, fid, size):
        root = self.server.root
        part = root / (fid + '.part')
        final = root / (fid + '.bin')
        if final.exists() and final.stat().st_size == size and file_digest(final) == fid:
            send(self.request, {'offset': size, 'complete': True})
            return
        offset = part.stat().st_size if part.exists() else 0
        if offset > size:
            part.unlink(); offset = 0
        send(self.request, {'offset': offset, 'complete': False})
        with part.open('ab') as stream:
            while offset < size:
                msg, chunk = receive(self.request)
                if msg.get('offset') != offset or not chunk or offset + len(chunk) > size or digest(chunk) != msg.get('sha256'):
                    send(self.request, {'error': 'Chunk offset or checksum mismatch'})
                    return
                stream.write(chunk); stream.flush(); os.fsync(stream.fileno())
                offset += len(chunk)
                send(self.request, {'ack': offset})
        if file_digest(part) != fid:
            part.unlink()
            send(self.request, {'error': 'Whole-file checksum mismatch; retry from zero'})
            return
        os.replace(part, final)
        send(self.request, {'verified': True, 'sha256': fid})
        print('VERIFIED', fid, size, flush=True)

class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--host', default='0.0.0.0'); p.add_argument('--port', type=int, default=9000); p.add_argument('--root', default='storage')
    a = p.parse_args(); root = Path(a.root); root.mkdir(parents=True, exist_ok=True)
    with Server((a.host, a.port), Handler) as server:
        server.root = root
        print('LISTENING', a.host, a.port, root, flush=True)
        server.serve_forever()
