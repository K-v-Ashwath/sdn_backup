"""Length-prefixed JSON header plus optional binary payload over TCP."""
import json, struct
MAX_FRAME = 2 * 1024 * 1024

def exact(sock, n):
    data = bytearray()
    while len(data) < n:
        part = sock.recv(n-len(data))
        if not part:
            raise ConnectionError('Peer disconnected')
        data.extend(part)
    return bytes(data)

def send(sock, obj, payload=b''):
    header = json.dumps(dict(obj, payload_length=len(payload))).encode()
    sock.sendall(struct.pack('!I', len(header)) + header + payload)

def receive(sock):
    n = struct.unpack('!I', exact(sock, 4))[0]
    if n > 65536:
        raise ValueError('Header too large')
    obj = json.loads(exact(sock, n))
    length = obj.pop('payload_length', 0)
    if not isinstance(length, int) or not 0 <= length <= MAX_FRAME:
        raise ValueError('Invalid payload length')
    return obj, exact(sock, length)
