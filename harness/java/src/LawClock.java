/*
 * LawClock -- a wall-clock reading in nanoseconds, and an honest statement of what it can resolve.
 *
 * The producer and the consumer are separate processes. A monotonic clock's origin is
 * process-relative, so subtracting one process's reading from another's would add each process's
 * start offset to every latency. Both sides therefore read the wall clock, which shares one epoch,
 * exactly as scripts/kafka_producer.py does with time.time_ns().
 *
 * Java's Instant.now() is backed by the same system call Python's time.time_ns() uses, but the
 * JDK's default clock is specified to have at best microsecond resolution, where Python reports
 * nanoseconds. That difference is small against the millisecond-scale trips this experiment
 * measures, and it is a difference between the two instruments being compared -- which is the
 * whole subject of A8. So it is not assumed: resolution() measures the smallest non-zero step this
 * JVM's clock actually produces, and the run records it. A comparison of two clients whose clocks
 * were never characterised would be a comparison of two clocks.
 */
import java.time.Instant;

final class LawClock {

    private LawClock() {
    }

    /** Wall-clock nanoseconds since the epoch, the same quantity Python's time.time_ns() gives. */
    static long nowNs() {
        Instant t = Instant.now();
        return t.getEpochSecond() * 1_000_000_000L + t.getNano();
    }

    /**
     * The finest step this clock must resolve before a run is worth taking, in nanoseconds.
     *
     * The trips this experiment measures run from under a millisecond to about fourteen, and the
     * cliff the law predicts is one tick -- a millisecond -- wide. A clock that cannot resolve a
     * tenth of that cannot see the structure the run exists to measure: every reading would be a
     * whole number of milliseconds, and A8 would be comparing two clocks rather than two clients.
     * Measured on a Windows JVM this clock steps in about a millisecond; on Linux, where the
     * testbed runs, the same call reads clock_gettime and steps far finer. The point of checking
     * rather than assuming is that the difference does not announce itself.
     */
    static final long FINEST_USABLE_NS = 100_000L;

    /**
     * Refuses to go on where the clock cannot resolve {@link #FINEST_USABLE_NS}.
     *
     * A run whose clock is too coarse does not look broken afterwards: it looks like a set of
     * tidy millisecond readings. Stopping here is the only point at which that is visible.
     */
    static long demandUsableResolution(String who) {
        long resolution = resolutionNs(200_000);
        if (resolution <= 0 || resolution > FINEST_USABLE_NS) {
            throw new IllegalStateException(
                    "STOP_RULE: " + who + " will not run on this clock: it steps in "
                    + resolution + " ns, and this experiment needs better than "
                    + FINEST_USABLE_NS + " ns. Every reading would be quantised above the effect "
                    + "being measured.");
        }
        return resolution;
    }

    /**
     * The smallest non-zero difference this clock produces, in nanoseconds, over `samples` reads.
     *
     * Returns 0 where every read was identical, which says the clock could not be characterised in
     * that many tries rather than that it is infinitely fine.
     */
    static long resolutionNs(int samples) {
        long finest = Long.MAX_VALUE;
        long previous = nowNs();
        for (int i = 0; i < samples; i++) {
            long current = nowNs();
            long step = current - previous;
            if (step > 0 && step < finest) {
                finest = step;
            }
            previous = current;
        }
        return finest == Long.MAX_VALUE ? 0L : finest;
    }
}
