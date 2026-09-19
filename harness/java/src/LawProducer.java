/*
 * LawProducer -- Kafka's official Java client, replaying the same plan our Python client replays
 * and writing the same producer.csv, so A8 compares two clients and not two harnesses.
 *
 * Everything that is not the client is held identical to scripts/kafka_producer.py: the plan is
 * read the same way and sorted the same way, the message carries the same fields, the key is the
 * event id, the settings are acks=all, linger 0 and one request in flight, and the three stamps
 * mean what they mean there --
 *
 *   t_prod_sched_ns   when the plan said this event should go, computed from one wall-clock origin
 *   t_prod_send_ns    the wall clock immediately before send returns a future
 *   t_broker_ack_ns   the wall clock when the broker's acknowledgement is seen
 *
 * The last of those is the one A8 is about. Where it is taken decides what it measures: in the
 * callback it is stamped on the client's own background thread, so the reading waits for that
 * thread to be scheduled and carries the scheduler's delay inside it; inline it is stamped on the
 * sending thread the moment the future resolves, and never pays that wait. Both are offered here,
 * as they are in the Python client, because the plan tests the note taken both ways.
 *
 * Usage:
 *   java -cp <kafka-clients and its logging jars>:. LawProducer \
 *     --run-id <id> --plan-csv <file> --out <producer.csv> --topic <topic> \
 *     --bootstrap host:port [--speedup 120] [--max-t-sim 600] [--ack-stamp callback|inline]
 */
import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Future;

import org.apache.kafka.clients.producer.KafkaProducer;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.clients.producer.RecordMetadata;
import org.apache.kafka.common.serialization.StringSerializer;

public final class LawProducer {

    /** One row of the replay plan: what to send and when the plan says to send it. */
    static final class PlannedEvent {
        final long rowIndex;
        final String matchId;
        final String eventId;
        final double tSimSeconds;
        final double tEmitOffsetSeconds;

        PlannedEvent(long rowIndex, String matchId, String eventId, double tSimSeconds,
                     double tEmitOffsetSeconds) {
            this.rowIndex = rowIndex;
            this.matchId = matchId;
            this.eventId = eventId;
            this.tSimSeconds = tSimSeconds;
            this.tEmitOffsetSeconds = tEmitOffsetSeconds;
        }
    }

    public static void main(String[] args) throws Exception {
        Map<String, String> opt = Args.parse(args);
        String runId = Args.need(opt, "run-id");
        String topic = Args.need(opt, "topic");
        Path planCsv = Paths.get(Args.need(opt, "plan-csv"));
        Path out = Paths.get(Args.need(opt, "out"));
        String bootstrap = opt.getOrDefault("bootstrap", "localhost:9092");
        double speedup = Double.parseDouble(opt.getOrDefault("speedup", "120.0"));
        double maxTSim = Double.parseDouble(opt.getOrDefault("max-t-sim", "600"));
        String ackStamp = opt.getOrDefault("ack-stamp", "callback");
        int maxInflight = Integer.parseInt(opt.getOrDefault("max-inflight", "1"));

        if (!ackStamp.equals("callback") && !ackStamp.equals("inline")) {
            throw new IllegalArgumentException("--ack-stamp must be callback or inline");
        }
        if (ackStamp.equals("inline") && maxInflight > 1) {
            // The same refusal the Python client makes, and for the same reason: above one request
            // in flight the blocking get() resolves an older event, not the one just sent.
            throw new IllegalArgumentException("--ack-stamp inline requires --max-inflight 1");
        }

        List<PlannedEvent> plan = readPlan(planCsv, maxTSim);
        // Sorted as the Python client sorts it: by simulated time, ties broken by the plan's own
        // row order, so both clients send the same events in the same order.
        plan.sort(Comparator.comparingDouble((PlannedEvent e) -> e.tSimSeconds)
                .thenComparingLong(e -> e.rowIndex));

        long clockResolutionNs = LawClock.demandUsableResolution("the producer");
        // Worded as the Python client words it, because run_integrity.py reads this line to check
        // the run used the setting the campaign asked for, and it must read both clients alike.
        System.out.println("CONFIG effective max_inflight=" + maxInflight
                + " ack_stamp=" + ackStamp + " client=java"
                + " clock_resolution_ns=" + clockResolutionNs);
        System.out.flush();

        Properties props = new Properties();
        props.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, bootstrap);
        props.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class.getName());
        props.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, StringSerializer.class.getName());
        props.put(ProducerConfig.ACKS_CONFIG, opt.getOrDefault("acks", "all"));
        props.put(ProducerConfig.LINGER_MS_CONFIG, opt.getOrDefault("linger-ms", "0"));
        props.put(ProducerConfig.MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION, String.valueOf(maxInflight));

        Map<String, Long> ackNs = new ConcurrentHashMap<>();
        List<String> errors = new ArrayList<>();

        long t0WallNs = LawClock.nowNs();
        long t0MonoNs = System.nanoTime();

        try (KafkaProducer<String, String> producer = new KafkaProducer<>(props);
             BufferedWriter writer = Files.newBufferedWriter(out, StandardCharsets.UTF_8)) {

            writer.write("run_id,backend,topic,event_id,match_id,t_sim_seconds,t_emit_offset_s,"
                    + "t_prod_sched_ns,t_prod_send_ns,t_broker_ack_ns");
            writer.newLine();

            List<String[]> rows = new ArrayList<>(plan.size());

            for (PlannedEvent event : plan) {
                long tProdSchedNs =
                        t0WallNs + (long) ((event.tEmitOffsetSeconds / speedup) * 1e9);
                // Wait on the monotonic clock, which is what a sleep should be measured against,
                // while the stamps themselves stay on the wall clock the consumer shares.
                long dueMonoNs = t0MonoNs + (long) ((event.tEmitOffsetSeconds / speedup) * 1e9);
                sleepUntil(dueMonoNs);

                String value = message(runId, event, tProdSchedNs);
                long tProdSendNs = LawClock.nowNs();
                ProducerRecord<String, String> record =
                        new ProducerRecord<>(topic, event.eventId, value);

                final String eventId = event.eventId;
                Future<RecordMetadata> future;
                if (ackStamp.equals("callback")) {
                    future = producer.send(record, (metadata, exception) -> {
                        if (exception != null) {
                            synchronized (errors) {
                                errors.add(eventId + ": " + exception);
                            }
                        } else {
                            ackNs.put(eventId, LawClock.nowNs());
                        }
                    });
                } else {
                    future = producer.send(record);
                }

                if (maxInflight <= 1) {
                    try {
                        future.get();
                        if (ackStamp.equals("inline")) {
                            // Stamped here, on this thread, the moment the future resolves.
                            ackNs.put(eventId, LawClock.nowNs());
                        }
                    } catch (Exception exc) {
                        synchronized (errors) {
                            errors.add(eventId + ": " + exc);
                        }
                    }
                }

                rows.add(new String[]{runId, "kafka", topic, event.eventId, event.matchId,
                        trim(event.tSimSeconds), trim(event.tEmitOffsetSeconds),
                        Long.toString(tProdSchedNs), Long.toString(tProdSendNs)});
            }

            producer.flush();

            for (String[] row : rows) {
                Long ack = ackNs.get(row[3]);
                writer.write(String.join(",", row));
                writer.write(",");
                writer.write(ack == null ? "" : Long.toString(ack));
                writer.newLine();
            }
        }

        if (!errors.isEmpty()) {
            System.err.println("SEND ERRORS: " + errors.size());
            for (String error : errors.subList(0, Math.min(10, errors.size()))) {
                System.err.println("  " + error);
            }
        }
        System.out.println("WROTE " + plan.size() + " rows to " + out);
    }

    /** The message the Python client sends, field for field, so the consumer cannot tell them apart. */
    private static String message(String runId, PlannedEvent event, long tEmitPlannedNs) {
        StringBuilder json = new StringBuilder(256);
        json.append('{');
        Json.field(json, "run_id", runId).append(',');
        Json.field(json, "match_id", event.matchId).append(',');
        Json.field(json, "event_id", event.eventId).append(',');
        json.append("\"t_sim_seconds\":").append(trim(event.tSimSeconds)).append(',');
        json.append("\"t_emit_offset_s\":").append(trim(event.tEmitOffsetSeconds)).append(',');
        json.append("\"t_emit_planned_ns\":").append(tEmitPlannedNs).append(',');
        Json.field(json, "s3_uid", event.matchId + ":" + event.eventId).append(',');
        json.append("\"s3_rev\":1,\"s3_is_correction\":false}");
        return json.toString();
    }

    /** Whole numbers without a trailing .0, as Python writes them, so the CSVs compare directly. */
    static String trim(double value) {
        if (value == Math.rint(value) && !Double.isInfinite(value)) {
            return Long.toString((long) value);
        }
        return Double.toString(value);
    }

    private static void sleepUntil(long dueMonoNs) {
        long remaining = dueMonoNs - System.nanoTime();
        while (remaining > 0) {
            try {
                Thread.sleep(remaining / 1_000_000L, (int) (remaining % 1_000_000L));
            } catch (InterruptedException exc) {
                Thread.currentThread().interrupt();
                return;
            }
            remaining = dueMonoNs - System.nanoTime();
        }
    }

    static List<PlannedEvent> readPlan(Path planCsv, double maxTSim) throws IOException {
        List<PlannedEvent> plan = new ArrayList<>();
        try (BufferedReader reader = Files.newBufferedReader(planCsv, StandardCharsets.UTF_8)) {
            String header = reader.readLine();
            if (header == null) {
                throw new IOException("the plan " + planCsv + " is empty");
            }
            Map<String, Integer> at = new HashMap<>();
            String[] names = header.split(",", -1);
            for (int i = 0; i < names.length; i++) {
                at.put(names[i].trim(), i);
            }
            for (String need : new String[]{"row_idx", "match_id", "event_id", "t_sim_seconds",
                    "t_emit_offset_s"}) {
                if (!at.containsKey(need)) {
                    throw new IOException("the plan " + planCsv + " has no column " + need);
                }
            }
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isEmpty()) {
                    continue;
                }
                String[] cell = line.split(",", -1);
                double tSim = Double.parseDouble(cell[at.get("t_sim_seconds")]);
                if (tSim > maxTSim) {
                    continue;
                }
                plan.add(new PlannedEvent(
                        Long.parseLong(cell[at.get("row_idx")]),
                        cell[at.get("match_id")],
                        cell[at.get("event_id")],
                        tSim,
                        Double.parseDouble(cell[at.get("t_emit_offset_s")])));
            }
        }
        return plan;
    }
}
