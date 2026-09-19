/*
 * LawConsumer -- Kafka's official Java client on the receiving side, writing the consumer.csv that
 * scripts/kafka_consumer.py writes, so the analysis cannot tell which client produced a run's files.
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
        try (KafkaConsumer<String, String> consumer = new KafkaConsumer<>(props);
             BufferedWriter writer = Files.newBufferedWriter(out, StandardCharsets.UTF_8)) {

            consumer.subscribe(Collections.singletonList(topic));
            writer.write("run_id,backend,topic,event_id,match_id,t_sim_seconds,t_cons_recv_ns,"
                    + "t_output_ns");
            writer.newLine();

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
                    written++;
                }
            }
        }
        System.out.println("WROTE " + written + " rows to " + out);
    }
}
