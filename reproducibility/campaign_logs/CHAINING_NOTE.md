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
