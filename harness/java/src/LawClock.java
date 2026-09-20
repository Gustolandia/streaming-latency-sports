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
     * Metrology's rule of ten: an instrument's resolution should divide the tolerance being
     * judged into about ten parts, and a ratio below four to one is not considered a measurement
     * of that tolerance at all. The tolerance here is not the cliff's width. It is the narrowest
     * quantity the plan pre-registers a bound on -- P2d asks whether the fitted start stays
     * within a quarter of a millisecond, and P3a whether the halfway point's whole interval sits
     * inside 0.25 ms either way. Ten parts of 250 microseconds is 25, so that is the bar; at the
     * 100 microseconds this first held, the ratio against those two bounds was 2.5 to 1, under
     * even the four-to-one floor, and the guard would have passed clocks too coarse to judge the
     * predictions it exists to protect.
     *
     * Measured: a Windows JVM steps in 998600 ns and a Windows Python in the same 998600 ns -- the
     * operating system's answer, not the runtime's, and about 1:1 against these bounds. On the
     * Linux testbed the JVM steps in 1000 ns and Python in 232 ns, which are 25:1 and 108:1. The
     * point of checking rather than assuming is that the difference does not announce itself.
     */
    static final long FINEST_USABLE_NS = 25_000L;

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
