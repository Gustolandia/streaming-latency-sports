/*
 * K1's arrival observer: an independent consumer, on the same host and the same wall clock as
 * the traced copy of Kafka's end-to-end tool, that writes down when each record became readable.
 *
 * It long-polls the topic's partitions from their end, so the broker answers its fetch as soon as
 * a record is there, and stamps every record of a poll with the wall clock read the moment the
 * poll returns. Its own lateness can only push its stamps later, which would make an early
 * arrival look less early: an observer that reads late understates the case K1 is after.
 *
 * It stops on its own once it has read as many records as it is told to expect, and writes its
 * rows out after every poll that returned any. In the pilot of 11 October it stopped only when it
 * was killed, and a kill does not empty a writer's buffer: every cell kept exactly 64 KB of rows,
 * the first 2,435 records of 3,000, and the last of them torn.
 *
 * Usage: java sbl.k1.ArrivalObserver broker_list topic seconds out.csv [expected_records]
 */
package sbl.k1;

import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.consumer.ConsumerRecords;
import org.apache.kafka.clients.consumer.KafkaConsumer;
import org.apache.kafka.common.TopicPartition;

import java.io.PrintWriter;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Properties;
import java.util.stream.Collectors;

public final class ArrivalObserver {

    private ArrivalObserver() {
    }

    static long wallMicros() {
        Instant now = Instant.now();
        return now.getEpochSecond() * 1_000_000L + now.getNano() / 1_000;
    }

    public static void main(String... args) throws Exception {
        if (args.length != 4 && args.length != 5) {
            throw new IllegalArgumentException(
                    "USAGE: java sbl.k1.ArrivalObserver broker_list topic seconds out.csv [expected_records]");
        }
        long expected = args.length == 5 ? Long.parseLong(args[4]) : Long.MAX_VALUE;
        Properties props = new Properties();
        props.put(ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, args[0]);
        props.put(ConsumerConfig.GROUP_ID_CONFIG, "sbl-k1-observer-" + System.currentTimeMillis());
        props.put(ConsumerConfig.ENABLE_AUTO_COMMIT_CONFIG, "false");
        props.put(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "latest");
        props.put(ConsumerConfig.FETCH_MIN_BYTES_CONFIG, "1");
        props.put(ConsumerConfig.FETCH_MAX_WAIT_MS_CONFIG, "500");
        props.put(ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG,
                "org.apache.kafka.common.serialization.ByteArrayDeserializer");
        props.put(ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG,
                "org.apache.kafka.common.serialization.ByteArrayDeserializer");
        long deadline = System.nanoTime() + Long.parseLong(args[2]) * 1_000_000_000L;
        try (KafkaConsumer<byte[], byte[]> consumer = new KafkaConsumer<>(props);
             PrintWriter out = new PrintWriter(args[3], "UTF-8")) {
            List<TopicPartition> parts = consumer.partitionsFor(args[1]).stream()
                    .map(p -> new TopicPartition(p.topic(), p.partition()))
                    .collect(Collectors.toList());
            consumer.assign(parts);
            consumer.seekToEnd(parts);
            consumer.assignment().forEach(consumer::position);
            out.println("partition,offset,arrival_us");
            System.out.println("observer ready");
            long read = 0;
            while (System.nanoTime() < deadline && read < expected) {
                ConsumerRecords<byte[], byte[]> records = consumer.poll(Duration.ofMillis(100));
                long at = wallMicros();
                for (ConsumerRecord<byte[], byte[]> r : records) {
                    out.println(r.partition() + "," + r.offset() + "," + at);
                }
                if (!records.isEmpty()) {
                    // After the stamp, never before it: writing out cannot make a stamp later.
                    out.flush();
                    read += records.count();
                }
            }
        }
    }
}
