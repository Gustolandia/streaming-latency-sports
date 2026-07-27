# A trap in the chained-campaign pattern

The `omb_chain*.sh` scripts run one after another, each waiting for its predecessor:

```bash
while pgrep -f 'omb_chain4.sh' >/dev/null 2>&1; do sleep 60; done
```

They were launched over ssh with

```bash
setsid nohup bash omb_chainN.sh > omb_chainN.log 2>&1 < /dev/null &
```

which leaves a `bash -c` wrapper process whose **command line contains the chain's filename**.
`pgrep -f` matches command lines, so that wrapper is indistinguishable from the chain itself. If a
wrapper outlives its child — and five were still alive an hour after launch, reparented to init —
the next chain waits forever on a process that has no work left to do. Six queued campaigns would
have stalled silently, with every process looking healthy in `ps`.

Fixed here by killing the wrappers, which is safe: children reparent to init rather than dying
with the parent, and all six chains kept running.

**If you reproduce this, avoid the trap rather than repairing it.** Either wait on the PID
directly:

```bash
while kill -0 "$PREV_PID" 2>/dev/null; do sleep 60; done
```

or wait on a sentinel the predecessor writes when it finishes, which also survives a chain that
dies without completing:

```bash
while [ ! -f .chain4.done ]; do sleep 60; done
```

The second is better: `pgrep` and `kill -0` both treat "the process is gone" as "the work is
done", which is false when the process was killed. A sentinel written as the last line of the
script distinguishes the two.

---

# The broker fills its own disk, and the provisioning did not stop it

`cloud/brokers.sh` sets `KAFKA_LOG_DIRS=/tmp/kraft-combined-logs`, which is a path **inside the
container**. There is no volume mount and, until 2026-07-27, no retention configuration. Every
topic segment a campaign produces therefore accumulates in the container's writable layer, and
nothing ever reclaims it.

On 2026-07-27 a campaign of roughly one hundred three-minute cells filled the broker host's 45 GB
root filesystem. Kafka died with exit code 1, port 19092 closed, and every subsequent cell failed
to connect. Seven cells were consumed before it was noticed.

**What worked.** The campaign's output-validation gate refused all seven: `Pub rate lines: 0`
produced `valid=0` with a reason and no count. No fabricated number reached the ledger, which is
exactly what that gate exists for.

**What did not.** Nothing watched the broker. The chain monitors tracked cell counts and campaign
logs, so a cell failing looked identical to a cell running, and the failure was found only by
reading a per-cell log for an unrelated reason. **A monitor that counts progress does not detect a
dependency dying.** If you reproduce this, watch the broker port directly, not just your own
harness's output.

**The fix**, now in both `brokers.sh` and `cluster_brokers.sh`:

```
-e KAFKA_LOG_RETENTION_MS=900000        # 15 minutes
-e KAFKA_LOG_RETENTION_BYTES=2147483648 # 2 GB
-e KAFKA_LOG_SEGMENT_BYTES=268435456    # 256 MB, so retention can act
```

Fifteen minutes and 2 GB are far more than any single three-minute cell needs, and cannot
accumulate across a campaign. `cluster_brokers.sh` matters more, not less: replication factor 3
means three copies of every segment, so a cluster host fills three times faster than the
single-node case that already did.

Without these the disk is a silent countdown whose length depends only on how many runs you do —
and the failure arrives as a benchmark that connects to nothing, not as a disk-space error.
