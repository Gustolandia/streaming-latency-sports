/*
 * LawConsumer -- Kafka's official Java client on the receiving side, writing the files that
 * scripts/kafka_consumer.py writes, so the analysis cannot tell which client produced a run.
 *
 * That is two files, not one. Beside consumer.csv the Python consumer writes consumer_events.csv,
 * and it is not an extra: scripts/pilot_checks.py reads the trip and the negative rate from it,
 * joined to producer.csv on event_id, and the campaign refuses a run whose consumer_events.csv is
 * missing. A client that wrote only consumer.csv would fail every run before it was ever judged,
 * and the quantity A8 compares between the two clients is the one computed from that file.
 *
 * The two stamps mean what they mean there: t_cons_recv_ns is the wall clock when the record is
 * taken out of the batch poll returned, and t_output_ns the wall clock after the row is formed.
 * Both are read from the same wall clock the producer reads, because the two run in separate
 * processes and a monotonic clock's origin would not be shared between them.
 *
 * It stops after --idle-seconds with no record for this run, as the Python consumer does, and it
 * ignores records belonging to another run on the same topic.
 *
 * Usage:
 *   java -cp <kafka-clients and its logging jars>:. LawConsumer \
 *     --run-id <id> --out <consumer.csv> --topic <topic> --bootstrap host:port \
 *     [--group <id>] [--idle-seconds 20]
 */
import java.io.BufferedWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.Duration;
import java.util.Collections;
import java.util.Map;
import java.util.Properties;

import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.consumer.ConsumerRecords;
import org.apache.kafka.clients.consumer.KafkaConsumer;
import org.apache.kafka.common.serialization.StringDeserializer;

public final class LawConsumer {

    public static void main(String[] args) throws Exception {
        Map<String, String> opt = Args.parse(args);
        String runId = Args.need(opt, "run-id");
        String topic = Args.need(opt, "topic");
        Path out = Paths.get(Args.need(opt, "out"));
        String bootstrap = opt.getOrDefault("bootstrap", "localhost:9092");
        String group = opt.getOrDefault("group", "sb-consumer-" + runId);
        double idleSeconds = Double.parseDouble(opt.getOrDefault("idle-seconds", "20"));

        long clockResolutionNs = LawClock.demandUsableResolution("the consumer");
        System.out.println("CONFIG client=java side=consumer clock_resolution_ns="
                + clockResolutionNs);
        System.out.flush();

        Properties props = new Properties();
        props.put(ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, bootstrap);
        props.put(ConsumerConfig.GROUP_ID_CONFIG, group);
        props.put(ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class.getName());
        props.put(ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG,
                StringDeserializer.class.getName());
        props.put(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest");
        props.put(ConsumerConfig.ENABLE_AUTO_COMMIT_CONFIG, "false");

        long written = 0;
        // Sibling of --out, named as the Python consumer names it: consumer.csv -> consumer_events.csv.
        Path events = eventsBeside(out);
        try (KafkaConsumer<String, String> consumer = new KafkaConsumer<>(props);
             BufferedWriter writer = Files.newBufferedWriter(out, StandardCharsets.UTF_8);
             BufferedWriter eventWriter = Files.newBufferedWriter(events, StandardCharsets.UTF_8)) {

            consumer.subscribe(Collections.singletonList(topic));
            writer.write("run_id,backend,topic,event_id,match_id,t_sim_seconds,t_cons_recv_ns,"
                    + "t_output_ns");
            writer.newLine();
            eventWriter.write("run_id,backend,topic,partition,offset,t_consume_ns,event_id,"
                    + "match_id,t_sim_seconds,t_emit_offset_s,t_emit_planned_ns,s3_uid,s3_rev,"
                    + "s3_is_correction");
            eventWriter.newLine();

            long idleNs = (long) (idleSeconds * 1e9);
            long lastRecordMonoNs = System.nanoTime();

            while (true) {
                ConsumerRecords<String, String> records = consumer.poll(Duration.ofMillis(200));
                if (records.isEmpty()) {
                    if (System.nanoTime() - lastRecordMonoNs >= idleNs) {
                        break;
                    }
                    continue;
                }
                for (ConsumerRecord<String, String> record : records) {
                    String value = record.value();
                    if (!runId.equals(Json.value(value, "run_id"))) {
                        continue;  // another run's records on the same topic are not ours
                    }
                    lastRecordMonoNs = System.nanoTime();

                    long tConsRecvNs = LawClock.nowNs();
                    String eventId = Json.value(value, "event_id");
                    String matchId = Json.value(value, "match_id");
                    String tSim = Json.value(value, "t_sim_seconds");
                    long tOutputNs = LawClock.nowNs();

                    writer.write(runId);
                    writer.write(",kafka,");
                    writer.write(topic);
                    writer.write(",");
                    writer.write(eventId == null ? "" : eventId);
                    writer.write(",");
                    writer.write(matchId == null ? "" : matchId);
                    writer.write(",");
                    writer.write(tSim == null ? "" : tSim);
                    writer.write(",");
                    writer.write(Long.toString(tConsRecvNs));
                    writer.write(",");
                    writer.write(Long.toString(tOutputNs));
                    writer.newLine();

                    // The same stamp under the name the event log gives it: the Python consumer
                    // sets t_cons_recv_ns = t_consume_ns from one read of the clock, and reading
                    // it twice here would put a poll's worth of scheduling between two numbers
                    // that are meant to be the same one.
                    eventWriter.write(runId);
                    eventWriter.write(",kafka,");
                    eventWriter.write(topic);
                    eventWriter.write(",");
                    eventWriter.write(Integer.toString(record.partition()));
                    eventWriter.write(",");
                    eventWriter.write(Long.toString(record.offset()));
                    eventWriter.write(",");
                    eventWriter.write(Long.toString(tConsRecvNs));
                    eventWriter.write(",");
                    eventWriter.write(eventId == null ? "" : eventId);
                    eventWriter.write(",");
                    eventWriter.write(matchId == null ? "" : matchId);
                    eventWriter.write(",");
                    eventWriter.write(tSim == null ? "" : tSim);
                    eventWriter.write(",");
                    eventWriter.write(field(value, "t_emit_offset_s"));
                    eventWriter.write(",");
                    eventWriter.write(field(value, "t_emit_planned_ns"));
                    eventWriter.write(",");
                    eventWriter.write(field(value, "s3_uid"));
                    eventWriter.write(",");
                    eventWriter.write(field(value, "s3_rev"));
                    eventWriter.write(",");
                    eventWriter.write(field(value, "s3_is_correction"));
                    eventWriter.newLine();
                    written++;
                }
            }
        }
        System.out.println("WROTE " + written + " rows to " + out + " and " + events);
    }

    /** A field of the message, or the empty cell the Python writer leaves when it is absent. */
    static String field(String message, String name) {
        String found = Json.value(message, name);
        return found == null ? "" : found;
    }

    /**
     * consumer.csv -> consumer_events.csv, beside it, as Path.with_name does on the Python side.
     *
     * Named from --out rather than from the run directory: under test --out is a temporary file,
     * and a hard-coded runs/&lt;run_id&gt;/ would write over a tracked one.
     */
    static Path eventsBeside(Path out) {
        String name = out.getFileName().toString();
        int dot = name.lastIndexOf('.');
        String stem = dot < 0 ? name : name.substring(0, dot);
        Path parent = out.getParent();
        String events = stem + "_events.csv";
        return parent == null ? Paths.get(events) : parent.resolve(events);
    }
}
