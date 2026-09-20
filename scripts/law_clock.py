"""The clock the experiment measures with, and the bar it has to clear.

Producer and consumer run as separate processes, so both read the wall clock: a monotonic clock's
origin is process-relative, and subtracting across processes would add each one's launch offset to
every latency.

What the wall clock cannot do is resolve finer than the operating system lets it, and that limit
does not announce itself. A run taken on a coarse clock does not look broken afterwards; it looks
like a set of tidy whole-millisecond readings, which is exactly the defect the tools audit found
in others. So it is measured before the run rather than inferred after it, the figure goes in the
run's own record, and a clock too coarse stops the run instead of quietly flattening it.

This is the Python side of the rule the Java client holds in LawClock.java. A8 compares our Python
client with Kafka's official Java one, and a guard that only one of them enforced would be one
more difference between them.
"""
import time

#: The finest step a clock must resolve before a run is worth taking, in nanoseconds.
#:
#: Metrology's rule of ten: an instrument should divide the tolerance being judged into about ten
#: parts, and below four to one it is not a measurement of that tolerance at all. The tolerance
#: here is not the cliff's width but the narrowest quantity the plan pre-registers a bound on --
#: P2d asks whether the fitted start stays within a quarter of a millisecond, and P3a whether the
#: halfway point's whole interval lies inside 0.25 ms either way. Ten parts of 250 microseconds is
#: 25. Measured: Windows steps in 998600 ns whether the runtime is the JVM or Python, which is the
#: operating system's answer and about 1:4 against that bound; the Linux testbed reads 1000 ns
#: from the JVM and 232 ns from Python, which are 25:1 and 108:1.
FINEST_USABLE_NS = 25_000

#: How many reads characterise the clock. Enough that a step is seen even where the clock is fine
#: and the loop outruns it, few enough to cost a fraction of a second once per run.
SAMPLES = 200_000


def now_ns():
    """Wall-clock epoch nanoseconds, shared across processes on one host."""
    return time.time_ns()


def resolution_ns(samples=SAMPLES, clock=None):
    """The smallest non-zero step this clock produces over `samples` reads.

    Returns 0 where every read was identical, which says the clock could not be characterised in
    that many tries rather than that it is infinitely fine -- the caller must treat the two
    differently, and `demand_usable_resolution` refuses both.
    """
    read = clock or now_ns
    finest = None
    previous = read()
    for _ in range(samples):
        current = read()
        step = current - previous
        previous = current
        if step <= 0:
            continue
        if finest is None or step < finest:
            finest = step
    return 0 if finest is None else finest


def demand_usable_resolution(who, samples=SAMPLES, clock=None):
    """The clock's resolution, or a stop where it is too coarse to measure the effect with.

    Stopping here is the only point at which a coarse clock is visible. Afterwards it is a column
    of round numbers that no check distinguishes from a real result.
    """
    resolution = resolution_ns(samples, clock)
    if resolution <= 0 or resolution > FINEST_USABLE_NS:
        raise SystemExit(
            "STOP_RULE: %s will not run on this clock: it steps in %d ns, and this experiment "
            "needs better than %d ns. Every reading would be quantised above the bounds P2d and "
            "P3a are judged against, so the run would look tidy and mean nothing."
            % (who, resolution, FINEST_USABLE_NS))
    return resolution
