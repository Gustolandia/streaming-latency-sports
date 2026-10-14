"""Probe on Linux: does so_timestamps get a transmit and a receive timestamp for every message on a
real TCP connection? A local echo server sends each message back after 5 ms; the client, with the
shim installed for the server's port, sends 20 messages (one blocking, one non-blocking style) and
reads the echoes. Run with the staged so_timestamps.py beside it."""
import socket
import sys
import threading
import time

sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else ".")
import so_timestamps as so  # noqa: E402

N = 20


def server(listener):
    conn, _ = listener.accept()
    got = b""
    while got.count(b"|") < N:
        data = conn.recv(65536)
        if not data:
            break
        got += data
        while b"|" in got:
            msg, got = got.split(b"|", 1)
            time.sleep(0.005)
            conn.sendall(msg + b"|")
            if msg.endswith(b"%06d" % (N - 1)):
                conn.close()
                return


base = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # the original class, for the server
base.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
base.bind(("127.0.0.1", 0))
base.listen(1)
port = base.getsockname()[1]
threading.Thread(target=server, args=(base,), daemon=True).start()

where = sys.argv[2] if len(sys.argv) > 2 else "software"
ledger = so.install([port], where)
c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
print("client class:", type(c).__name__)
c.connect(("127.0.0.1", port))
c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
sent_at = {}
for i in range(N):
    eid = "constant-%06d" % i
    payload = (b'{"key":"' + eid.encode() + b'","value":{"event_id":"' + eid.encode() + b'"}}|')
    sent_at[eid] = time.time_ns()
    if i % 2:
        c.sendall(payload)
    else:
        c.send(payload)
    time.sleep(0.02)
buf = bytearray(4096)
got = b""
reads = 0
while got.count(b"|") < N:
    if reads % 2:
        n = c.recv_into(buf)
        data = bytes(buf[:n])
    else:
        data = c.recv(4096)
    reads += 1
    if not data:
        break
    got += data
c.close()
summary = ledger.write("/tmp/so_probe.csv")
print("summary:", summary)
tx, rx = ledger.transmit_times(), ledger.receive_times()
bad = []
for i in range(N):
    eid = "constant-%06d" % i
    t, r = tx.get(eid), rx.get(eid)
    if t is None or r is None:
        bad.append((eid, t, r))
        continue
    if i < 3 or i == N - 1:
        print(eid, "tx-after-call us %.1f" % ((t - sent_at[eid]) / 1e3),
              "rx-tx ms %.3f" % ((r - t) / 1e6))
print("missing:", bad)
print("all timed:", not bad, "| tx keys:", sorted(ledger.streams[0].keys)[:5], "...")
