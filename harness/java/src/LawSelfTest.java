/*
 * LawSelfTest -- checks the parts of the Java harness that do not need a broker.
 *
 * The client's job is to be indistinguishable from the Python one everywhere except the client
 * itself, so what is checked here is exactly that: the clock reads a wall time that matches the
 * system's and resolves finely enough to be worth using, the message escapes what it must and
 * reads back what it wrote, and the plan is read and ordered the way the Python client reads and
 * orders it. Anything that fails here would make A8 a comparison of two harnesses.
 *
 * Run: java -cp out LawSelfTest
 */
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

public final class LawSelfTest {

    private static int failures = 0;

    public static void main(String[] args) throws Exception {
        clockReadsTheWallWithTheSameEpoch();
        clockResolutionIsFineEnoughToMeasureWith();
        aMessageReadsBackWhatItWrote();
        aQuoteInAnIdentifierDoesNotBreakTheMessage();
        aNumberFieldIsReadWithoutItsQuotes();
        anAbsentFieldIsAbsentRatherThanEmpty();
        thePlanIsReadAndFilteredBySimulatedTime();
        wholeNumbersAreWrittenWithoutATrailingPoint();

        if (failures > 0) {
            System.out.println(failures + " CHECK(S) FAILED");
            System.exit(1);
        }
        System.out.println("all checks passed");
    }

    private static void clockReadsTheWallWithTheSameEpoch() {
        long java = LawClock.nowNs();
        long system = System.currentTimeMillis() * 1_000_000L;
        // Within a second of the system's own wall clock: the same epoch, not a monotonic origin.
        check("the clock reads wall time", Math.abs(java - system) < 1_000_000_000L,
                "java=" + java + " system=" + system);
    }

    private static void clockResolutionIsFineEnoughToMeasureWith() {
        long resolution = LawClock.resolutionNs(200_000);
        boolean usable = resolution > 0 && resolution <= LawClock.FINEST_USABLE_NS;
        System.out.println("  clock resolution here: " + resolution + " ns on "
                + System.getProperty("os.name"));
        // Not a failure of this code: it is a fact about the machine running it, and the client
        // refuses to run where it holds. What is checked is that the refusal works both ways.
        if (!usable) {
            System.out.println("     (too coarse to run A8 here; the client will refuse)");
        }
        boolean refused = false;
        try {
            LawClock.demandUsableResolution("the self test");
        } catch (IllegalStateException stop) {
            refused = true;
        }
        check("the clock guard agrees with the measurement", refused == !usable,
                "usable=" + usable + " refused=" + refused);
    }

    private static void aMessageReadsBackWhatItWrote() {
        StringBuilder json = new StringBuilder("{");
        Json.field(json, "run_id", "law_a8_r001").append(',');
        Json.field(json, "event_id", "constant-000007").append('}');
        String message = json.toString();
        check("run_id reads back", "law_a8_r001".equals(Json.value(message, "run_id")),
                Json.value(message, "run_id"));
        check("event_id reads back", "constant-000007".equals(Json.value(message, "event_id")),
                Json.value(message, "event_id"));
    }

    private static void aQuoteInAnIdentifierDoesNotBreakTheMessage() {
        StringBuilder json = new StringBuilder("{");
        Json.field(json, "event_id", "od\"d\\one").append('}');
        String read = Json.value(json.toString(), "event_id");
        check("a quote and a backslash survive the round trip", "od\"d\\one".equals(read), read);
    }

    private static void aNumberFieldIsReadWithoutItsQuotes() {
        String message = "{\"t_sim_seconds\":42,\"s3_rev\":1}";
        check("a number reads as its digits", "42".equals(Json.value(message, "t_sim_seconds")),
                Json.value(message, "t_sim_seconds"));
    }

    private static void anAbsentFieldIsAbsentRatherThanEmpty() {
        check("an absent field is null", Json.value("{\"a\":1}", "b") == null,
                String.valueOf(Json.value("{\"a\":1}", "b")));
    }

    private static void thePlanIsReadAndFilteredBySimulatedTime() throws IOException {
        Path plan = Files.createTempFile("plan", ".csv");
        try {
            Files.write(plan, String.join("\n",
                    "row_idx,match_id,event_id,t_sim_seconds,t_emit_offset_s",
                    "2,900000,c-2,5,0.04",
                    "0,900000,c-0,0,0.0",
                    "1,900000,c-1,5,0.02",
                    "3,900000,c-3,900,7.5").getBytes(StandardCharsets.UTF_8));
            var read = LawProducer.readPlan(plan, 600);
            check("an event past the horizon is left out", read.size() == 3,
                    "read " + read.size());
            read.sort(java.util.Comparator
                    .comparingDouble((LawProducer.PlannedEvent e) -> e.tSimSeconds)
                    .thenComparingLong(e -> e.rowIndex));
            // Ties on simulated time keep the plan's own order, as the Python client's stable sort
            // does: c-1 was row 1 and c-2 row 2, so c-1 goes first however the file listed them.
            check("ties keep the plan's own order",
                    read.get(0).eventId.equals("c-0") && read.get(1).eventId.equals("c-1")
                            && read.get(2).eventId.equals("c-2"),
                    read.get(0).eventId + "," + read.get(1).eventId + "," + read.get(2).eventId);
        } finally {
            Files.deleteIfExists(plan);
        }
    }

    private static void wholeNumbersAreWrittenWithoutATrailingPoint() {
        // Python writes 0 and 5, not 0.0 and 5.0, and the two CSVs are compared directly.
        check("a whole number has no trailing point", "5".equals(LawProducer.trim(5.0)),
                LawProducer.trim(5.0));
        check("a fraction keeps its digits", "0.02".equals(LawProducer.trim(0.02)),
                LawProducer.trim(0.02));
    }

    private static void check(String what, boolean held, String saw) {
        if (held) {
            System.out.println("ok   " + what);
        } else {
            System.out.println("FAIL " + what + " (saw: " + saw + ")");
            failures++;
        }
    }
}
