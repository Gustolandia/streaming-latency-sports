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
 * Each record is identified as the broker identifies it, by the partition and offset the client
 * hands back with it (ConsumerRecord.partition() and offset()). The message's run_id decides only
 * whether a record is this run's, and its event_id is copied into its column.
 *
 * The group protocol is the classic one. Under it the consumer has no network thread: the thread
 * that calls poll() builds each fetch and sends it, and sends the next one just before poll()
 * hands back the records it has (ClassicKafkaConsumer.poll and pollForFetches, kafka-clients
 * 3.9.0), and a broker never has more than one fetch from it outstanding
 * (AbstractFetch.prepareFetchRequests). A message that reaches the broker while this thread works
 * on the last batch, after that fetch was answered, waits there for the thread's next poll(). The
 * heartbeat thread polls the same network client between heartbeats and may read an answer off
 * the socket, but it builds no fetch. kafka-clients 3.9.0 has a network thread of its own only
 * under the newer group protocol (group.protocol=consumer, its consumer_background_thread), which
 * this client does not use.
 *
 * So the poll thread is the one whose scheduling decides when fetches leave. It is named law-poll,
 * in the kernel too, so that the kit can find it and set its policy (chrt -f -p 80 <tid>), and
 * --threads-out writes, once the group has assigned the partitions, every thread of the process:
 * its kernel id, the kernel's name for it, its role, and the JVM's name for it.
 *
 * Usage:
 *   java -cp <kafka-clients and its logging jars>:. LawConsumer \
 *     --run-id <id> --out <consumer.csv> --topic <topic> --bootstrap host:port \
 *     [--group <id>] [--idle-seconds 20] [--threads-out <threads.csv>]
 */
import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Properties;

import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.consumer.ConsumerRecords;
import org.apache.kafka.clients.consumer.KafkaConsumer;
import org.apache.kafka.common.serialization.StringDeserializer;

public final class LawConsumer {

    /** The name the poll thread gives itself; the kernel keeps its first 15 bytes. */
    static final String POLL_THREAD = "law-poll";

    /** --threads-out's columns, the same in scripts/kafka_consumer_confluent.py and harness/go. */
    static final String THREAD_HEADER = "tid,name,role,runtime_name";

    public static void main(String[] args) throws Exception {
        Map<String, String> opt = Args.parse(args);
        String runId = Args.need(opt, "run-id");
        String topic = Args.need(opt, "topic");
        Path out = Paths.get(Args.need(opt, "out"));
        String bootstrap = opt.getOrDefault("bootstrap", "localhost:9092");
        String group = opt.getOrDefault("group", "sb-consumer-" + runId);
        double idleSeconds = Double.parseDouble(opt.getOrDefault("idle-seconds", "20"));
        String threadsOut = opt.get("threads-out");

        // 23 Oct 2026: this thread sends the fetches, and the kit sets its policy by name. HotSpot
        // hands the kernel a thread's new name when the thread renames itself and was not attached
        // through JNI, as this one, the main thread, was not (JVM_SetNativeThreadName,
        // os::set_native_thread_name), so the name is in /proc/<pid>/task/<tid>/comm as well.
        Thread.currentThread().setName(POLL_THREAD);

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
        // 23 Oct 2026: the classic group protocol, kafka-clients 3.9.0's default and the only one
        // kafka-python 2.3.2 speaks, named so that a later default cannot change it under a block.
        props.put(ConsumerConfig.GROUP_PROTOCOL_CONFIG, "classic");

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
            boolean listed = threadsOut == null;

            while (true) {
                ConsumerRecords<String, String> records = consumer.poll(Duration.ofMillis(200));
                if (!listed && !consumer.assignment().isEmpty()) {
                    // 23 Oct 2026: the group assigns the partitions inside poll(), and the
                    // threads are listed as soon as a poll returns with them.
                    writeThreads(Paths.get(threadsOut));
                    listed = true;
                }
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
            if (!listed) {
                // 23 Oct 2026: never assigned, the list is written still, while the client's
                // threads are alive, so that the run's record holds it.
                writeThreads(Paths.get(threadsOut));
            }
        }
        // 23 Oct 2026: the line every consumer ends with, as scripts/kafka_consumer.py ends, one
        // for each file it wrote.
        System.out.println("OK java consumer: wrote " + written + " rows -> " + out);
        System.out.println("OK java consumer: wrote " + written + " rows -> " + events);
    }

    /** A field of the message, or the empty cell the Python writer leaves when it is absent. */
    static String field(String message, String name) {
        String found = Json.value(message, name);
        return found == null ? "" : found;
    }

    /**
     * Writes every thread of this process: its kernel id, the kernel's name for it, its role, and
     * the JVM's name for it, under {@link #THREAD_HEADER}.
     *
     * Called from the poll thread, which finds its own kernel id in /proc/thread-self and is the
     * row whose role is poll+fetch. The JVM's names are matched to the kernel's by their first 15
     * bytes, which is what HotSpot hands the kernel; a name two threads share is left out. Where
     * the kernel lists no threads, the JVM's own list is written without ids, which is what there
     * is. The list goes to a file beside the path and is then moved onto it, so that the kit,
     * which waits for the file, never reads half of one.
     */
    static int writeThreads(Path into) throws IOException {
        Path tasks = Paths.get("/proc/self/task");
        String self = "";
        try {
            self = Files.readSymbolicLink(Paths.get("/proc/thread-self")).getFileName().toString();
        } catch (IOException | UnsupportedOperationException notLinux) {
            // No /proc/thread-self: no row is marked as the poll thread's.
        }
        List<Thread> jvm = jvmThreads();
        Map<String, List<String>> byKernelName = new HashMap<>();
        for (Thread thread : jvm) {
            byKernelName.computeIfAbsent(kernelName(thread.getName()), k -> new ArrayList<>())
                    .add(thread.getName());
        }
        List<Long> ids = new ArrayList<>();
        try (DirectoryStream<Path> entries = Files.newDirectoryStream(tasks)) {
            for (Path entry : entries) {
                ids.add(Long.parseLong(entry.getFileName().toString()));
            }
        } catch (IOException noList) {
            System.err.println("LawConsumer: no thread list to read (" + noList
                    + "); the JVM's own threads are written without their kernel ids");
        }
        Collections.sort(ids);
        List<String> rows = new ArrayList<>();
        rows.add(THREAD_HEADER);
        for (long id : ids) {
            String name;
            try {
                name = new String(Files.readAllBytes(tasks.resolve(Long.toString(id))
                        .resolve("comm")), StandardCharsets.UTF_8);
            } catch (IOException ended) {
                continue;  // the thread ended between the listing and this read
            }
            name = name.endsWith("\n") ? name.substring(0, name.length() - 1) : name;
            boolean poll = Long.toString(id).equals(self);
            List<String> named = byKernelName.get(name);
            String runtime = poll ? Thread.currentThread().getName()
                    : named != null && named.size() == 1 ? named.get(0) : "";
            rows.add(id + "," + cell(name) + "," + (poll ? "poll+fetch" : "") + "," + cell(runtime));
        }
        if (ids.isEmpty()) {
            for (Thread thread : jvm) {
                rows.add(",," + (thread == Thread.currentThread() ? "poll+fetch" : "") + ","
                        + cell(thread.getName()));
            }
        }
        Path parent = into.toAbsolutePath().getParent();
        if (parent != null) {
            Files.createDirectories(parent);
        }
        Path partial = into.resolveSibling(into.getFileName() + ".tmp");
        Files.write(partial, rows, StandardCharsets.UTF_8);
        Files.move(partial, into, StandardCopyOption.REPLACE_EXISTING,
                StandardCopyOption.ATOMIC_MOVE);
        System.out.println("OK threads: " + (rows.size() - 1) + " listed -> " + into);
        return rows.size() - 1;
    }

    /**
     * The JVM's live threads, from the root thread group. Thread.getAllStackTraces() would list
     * them too, but it stops every thread at a safepoint to walk their stacks, and this list may
     * be written while messages are arriving.
     */
    static List<Thread> jvmThreads() {
        ThreadGroup root = Thread.currentThread().getThreadGroup();
        while (root.getParent() != null) {
            root = root.getParent();
        }
        Thread[] found = new Thread[root.activeCount() + 64];
        int n = root.enumerate(found, true);
        return Arrays.asList(found).subList(0, n);
    }

    /** A thread's name as the kernel keeps it: at most 15 bytes of UTF-8 (TASK_COMM_LEN, 16). */
    static String kernelName(String name) {
        byte[] bytes = name.getBytes(StandardCharsets.UTF_8);
        return bytes.length <= 15 ? name : new String(bytes, 0, 15, StandardCharsets.UTF_8);
    }

    /** A CSV cell, quoted where it holds a comma, a quote or a line break. */
    static String cell(String value) {
        if (value.indexOf(',') < 0 && value.indexOf('"') < 0 && value.indexOf('\n') < 0
                && value.indexOf('\r') < 0) {
            return value;
        }
        return '"' + value.replace("\"", "\"\"") + '"';
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
