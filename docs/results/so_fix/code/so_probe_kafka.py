"""Probe on the driver: why does kafka-python fail to reach the broker with the shim installed?
Connects a KafkaProducer with kafka's debug log on, the shim installed for the bootstrap port."""
import logging
import sys
import traceback

sys.path.insert(0, sys.argv[1])
import so_timestamps as so  # noqa: E402

logging.basicConfig(level=logging.DEBUG, format="%(name)s %(levelname)s %(message)s")
for noisy in ("kafka.metrics", "kafka.protocol"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

ledger = so.install([19092], "sched")
real_send = so._send


def spy(name, fn):
    def wrapped(*a):
        try:
            out = fn(*a)
            print("SPY", name, "ok", type(out).__name__, flush=True)
            return out
        except BaseException as exc:
            print("SPY", name, "raised", repr(exc), flush=True)
            raise
    return wrapped


for name in ("_getpeername", "_setsockopt", "_send", "_sendall", "_recv", "_recv_into",
             "_recvmsg", "_recvmsg_into"):
    setattr(so, name, spy(name, getattr(so, name)))

from kafka import KafkaProducer  # noqa: E402
try:
    p = KafkaProducer(bootstrap_servers=sys.argv[2] if len(sys.argv) > 2 else "10.1.1.21:19092",
                      request_timeout_ms=5000, api_version_auto_timeout_ms=5000)
    print("CONNECTED", p.config.get("api_version"))
    p.close()
except Exception:
    traceback.print_exc()
print("counts", ledger.counts)
