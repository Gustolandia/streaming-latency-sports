"""Probe on the driver: which transmit timestamps does the kernel give on the real network path to
the broker? Sends 20 Redis ECHO commands, each carrying an event id, to the broker's Redis, with the
shim taking the transmit timestamp where argv[2] says, and reads the replies."""
import socket
import sys
import time

sys.path.insert(0, sys.argv[1])
import so_timestamps as so  # noqa: E402

where = sys.argv[2]
broker = sys.argv[3] if len(sys.argv) > 3 else "10.1.1.21"
ledger = so.install([6379], where)
c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
c.connect((broker, 6379))
c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
calls = {}
for i in range(20):
    eid = "constant-%06d" % i
    cmd = b"*2\r\n$4\r\nECHO\r\n$15\r\n" + eid.encode() + b"\r\n"
    calls[eid] = time.time_ns()
    c.sendall(cmd)
    got = b""
    while not got.endswith(b"\r\n") or got.count(b"\r\n") < 2:
        got += c.recv(4096)
    time.sleep(0.02)
c.close()
tx, rx = ledger.transmit_times(), ledger.receive_times()
print(where, "counts:", {k: ledger.counts[k] for k in ("transmit_timestamps", "other_queue_entries",
                                                     "reads", "reads_without_timestamp")})
timed = [e for e in calls if tx.get(e) is not None and rx.get(e) is not None]
print(where, "ids with both timestamps:", len(timed), "of", len(calls))
for e in timed[:3]:
    print("  %s tx-after-call %.1f us, rx-tx %.1f us" % (e, (tx[e] - calls[e]) / 1e3,
                                                        (rx[e] - tx[e]) / 1e3))
