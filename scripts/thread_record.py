#!/usr/bin/env python3
"""
thread_record.py -- which of a client's threads wrote which timestamp, and the two clocks' offset.

A negative reading is a message whose arrival was stamped before its acknowledgement was. The law
says why: the thread that stamps the acknowledgement -- kafka-python's own network thread, through
the delivery callback, or the Redis producer's send workers -- sat in the run queue behind the
load while the message crossed to the receiver. A recording of that thread's waits can show it
message by message (A9, D28-1), but only if the recording can tell that thread from every other
thread named python3, and only if its clock can be laid against the clients' own.

So a client asked to (--thread-record) notes the native id of each thread the first time it stamps
something, under the name of what it stamps, and writes them beside its output with a reading of
both clocks at the start and at the end: the kernel's tracer counts in CLOCK_MONOTONIC, and the
clients stamp in CLOCK_REALTIME. Noting costs one attribute look-up per stamp after the first.

It is asked for, not always written, because A8's two clients must leave indistinguishable files,
and the Java one keeps no such record.
"""
import json
import os
import threading
import time


def clock_pair():
    """Both clocks, read back to back: the offset between them, to within the gap."""
    return {"realtime_ns": time.time_ns(), "monotonic_ns": time.monotonic_ns()}


class ThreadRecord:
    """The threads that stamp, by what they stamp, and the clocks at start and end."""

    def __init__(self):
        self._lock = threading.Lock()
        self._noted = threading.local()
        self.roles = {}
        self.clocks = [clock_pair()]

    def note(self, role):
        """Record the calling thread's native id under `role`, once per thread and role."""
        if getattr(self._noted, role, False):
            return
        setattr(self._noted, role, True)
        tid = threading.get_native_id()
        with self._lock:
            self.roles.setdefault(role, set()).add(tid)

    def write(self, path):
        """Write the record, with a last reading of the clocks, and return what was written."""
        self.clocks.append(clock_pair())
        with self._lock:
            found = {"pid": os.getpid(),
                     "roles": dict((role, sorted(tids)) for role, tids in sorted(self.roles.items())),
                     "clocks": list(self.clocks)}
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(found, indent=2, sort_keys=True) + "\n")
        return found


def beside(out_path):
    """Where a client's record goes: next to its CSV, named after it."""
    root, _ext = os.path.splitext(str(out_path))
    return root + "_threads.json"
