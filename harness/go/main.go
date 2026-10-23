// Command franz-consumer is a Kafka consumer on franz-go (github.com/twmb/franz-go/pkg/kgo) that
// writes the files scripts/kafka_consumer.py writes, so that the reader and the integrity rule
// cannot tell which client produced a run.
//
// It consumes one topic in a group of its own from the earliest offset, reads the producer's JSON
// payload, skips any message whose run_id is not this run's, and stops after --idle-seconds with
// no message of this run. Each message is identified as the broker identifies it, by the partition
// and offset franz-go hands back with it; the payload's event_id is only copied into its column.
//
// The stamps are kafka_consumer.py's. t_consume_ns is time.Now().UnixNano(), the wall clock,
// which Go reads with clock_gettime(CLOCK_REALTIME) on Linux (time.now in
// runtime/time_linux_amd64.s on x86-64, walltime in runtime/sys_linux_arm64.s on arm64), taken
// when the program has the message from PollFetches; t_cons_recv_ns is the same reading, and
// t_output_ns the next one.
//
// franz-go fetches in goroutines of its own. Each broker's source keeps one fetch buffered for
// the program and issues the next one as soon as the program takes the buffered one, which
// PollFetches does (source.loopFetch and takeBuffered, pkg/kgo/source.go, v1.19.5). The request is
// written by the broker connection's request goroutine and its answer read by its response
// goroutine (handleReqs and handleResps, pkg/kgo/broker.go), each started when its queue gains an
// entry and ended when the queue empties. Go's scheduler runs goroutines on whichever of the
// process's OS threads is free, and franz-go names none of them, so no OS thread is the fetching
// thread; README.md says what that leaves the kit.
//
// --threads-out writes, once the group has assigned the partitions, each of the process's OS
// threads with the kernel's name for it, which for every one is the program's own.
package main

import (
	"context"
	"encoding/csv"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"runtime/debug"
	"sort"
	"strconv"
	"strings"
	"sync/atomic"
	"time"

	"github.com/twmb/franz-go/pkg/kgo"
)

// consumerColumns and eventColumns are consumer.csv's and consumer_events.csv's columns, as
// scripts/kafka_consumer.py writes them.
var consumerColumns = []string{"run_id", "backend", "topic", "event_id", "match_id",
	"t_sim_seconds", "t_cons_recv_ns", "t_output_ns"}

var eventColumns = []string{"run_id", "backend", "topic", "partition", "offset",
	"t_consume_ns", "event_id", "match_id", "t_sim_seconds", "t_emit_offset_s",
	"t_emit_planned_ns", "s3_uid", "s3_rev", "s3_is_correction"}

// copied are the message's fields the event log copies after its event_id, in its order.
var copied = []string{"match_id", "t_sim_seconds", "t_emit_offset_s", "t_emit_planned_ns",
	"s3_uid", "s3_rev", "s3_is_correction"}

// threadColumns are --threads-out's columns, the same in scripts/kafka_consumer_confluent.py and
// harness/java/src/LawConsumer.java.
var threadColumns = []string{"tid", "name", "role", "runtime_name"}

const (
	// tasks is where the kernel lists this process's threads: one directory per thread id, each
	// with the thread's name in comm.
	tasks = "/proc/self/task"

	// pollWait is how long one PollFetches waits for a fetch, as long as kafka_consumer.py's
	// poll waits by default (--poll-timeout-ms 1000).
	pollWait = time.Second

	// flushEvery is how many messages go between flushes of the two files, as in
	// kafka_consumer.py.
	flushEvery = 2000

	// finestUsableNs is the coarsest clock step a run may be made with: scripts/law_clock.py's
	// FINEST_USABLE_NS and LawClock.FINEST_USABLE_NS in harness/java.
	finestUsableNs = 25000

	// clockSamples is how many reads characterise the clock, as in scripts/law_clock.py.
	clockSamples = 200000
)

func main() {
	os.Exit(run(os.Args[1:]))
}

// run is the consumer, from its command line to its exit status.
func run(argv []string) int {
	flags := flag.NewFlagSet("franz-consumer", flag.ContinueOnError)
	bootstrap := flags.String("bootstrap", "localhost:9092",
		"the brokers to start from, host:port[,host:port]")
	topic := flags.String("topic", "sb-events", "the topic to consume")
	group := flags.String("group", "", "the consumer group (default sb-consumer-<run-id>)")
	runID := flags.String("run-id", "",
		"this run's id; a message whose run_id differs is skipped (required)")
	out := flags.String("out", "", "consumer.csv; consumer_events.csv is written beside it (required)")
	idleSeconds := flags.Float64("idle-seconds", 15,
		"stop after this many seconds with no message of this run")
	threadsOut := flags.String("threads-out", "",
		"once the partitions are assigned, write this process's threads to this CSV")
	if err := flags.Parse(argv); err != nil {
		return 2
	}
	if *runID == "" || *out == "" {
		fmt.Fprintln(os.Stderr, "franz-consumer: --run-id and --out are required")
		return 2
	}

	// 23 Oct 2026: every client of the block measures its clock before a run and refuses one
	// that steps coarser than 25 microseconds (scripts/law_clock.py), and which build ran is part
	// of what the block reports.
	resolution := clockResolutionNs(clockSamples)
	if resolution <= 0 || resolution > finestUsableNs {
		fmt.Fprintf(os.Stderr, "STOP_RULE: the franz-go consumer will not run on this clock: it "+
			"steps in %d ns, and this experiment needs better than %d ns.\n",
			resolution, finestUsableNs)
		return 1
	}
	fmt.Printf("CONFIG effective client=franz-go franz_go=%s go=%s clock_resolution_ns=%d\n",
		moduleVersion("github.com/twmb/franz-go"), runtime.Version(), resolution)

	groupID := *group
	if groupID == "" {
		groupID = "sb-consumer-" + *runID
	}
	eventsPath := beside(*out)
	if err := os.MkdirAll(filepath.Dir(*out), 0o755); err != nil {
		fmt.Fprintln(os.Stderr, "franz-consumer:", err)
		return 1
	}

	var assigned atomic.Bool
	client, err := kgo.NewClient(
		kgo.SeedBrokers(strings.Split(*bootstrap, ",")...),
		kgo.ConsumerGroup(groupID),
		kgo.ConsumeTopics(*topic),
		kgo.ConsumeResetOffset(kgo.NewOffset().AtStart()),
		// 23 Oct 2026: the topic is named for the run and made by whichever client first asks
		// the broker for it, and the kit starts the consumer two seconds before the producer.
		// Kafka's Java consumer asks for a topic it subscribes to to be made, by default; franz-go
		// does so only when told to (AllowAutoTopicCreation, v1.19.5).
		kgo.AllowAutoTopicCreation(),
		kgo.OnPartitionsAssigned(func(context.Context, *kgo.Client, map[string][]int32) {
			assigned.Store(true)
		}),
	)
	if err != nil {
		fmt.Fprintln(os.Stderr, "franz-consumer:", err)
		return 1
	}

	consumerTable, err := create(*out, consumerColumns)
	if err != nil {
		fmt.Fprintln(os.Stderr, "franz-consumer:", err)
		client.Close()
		return 1
	}
	eventsTable, err := create(eventsPath, eventColumns)
	if err != nil {
		fmt.Fprintln(os.Stderr, "franz-consumer:", err)
		consumerTable.close()
		client.Close()
		return 1
	}

	idle := time.Duration(*idleSeconds * float64(time.Second))
	lastMessage := time.Now()
	listed := *threadsOut == ""
	written := 0
	status := 0
poll:
	for {
		ctx, cancel := context.WithTimeout(context.Background(), pollWait)
		fetches := client.PollFetches(ctx)
		cancel()
		if !listed && assigned.Load() {
			if err := writeThreads(*threadsOut); err != nil {
				fmt.Fprintln(os.Stderr, "franz-consumer:", err)
				status = 1
				break poll
			}
			listed = true
		}
		if fetches.IsClientClosed() {
			break
		}
		for _, failed := range fetches.Errors() {
			// An empty poll comes back as the context's own error, and is not one.
			if !errors.Is(failed.Err, context.DeadlineExceeded) {
				fmt.Fprintf(os.Stderr, "franz-consumer: %s[%d]: %v\n",
					failed.Topic, failed.Partition, failed.Err)
			}
		}
		if fetches.NumRecords() == 0 {
			if time.Since(lastMessage) >= idle {
				break
			}
			continue
		}
		for _, record := range fetches.Records() {
			fields := map[string]json.RawMessage{}
			if err := json.Unmarshal(record.Value, &fields); err != nil {
				fmt.Fprintf(os.Stderr, "franz-consumer: the message at %s[%d] offset %d is not "+
					"the producer's JSON: %v\n", record.Topic, record.Partition, record.Offset, err)
				status = 1
				break poll
			}
			if id, ok := text(fields["run_id"]); !ok || id != *runID {
				continue
			}
			received := time.Now()
			lastMessage = received
			tConsume := strconv.FormatInt(received.UnixNano(), 10)
			tOutput := strconv.FormatInt(time.Now().UnixNano(), 10)
			eventID := pythonCell(fields["event_id"])
			row := []string{*runID, "kafka", *topic, eventID, pythonCell(fields["match_id"]),
				pythonCell(fields["t_sim_seconds"]), tConsume, tOutput}
			event := []string{*runID, "kafka", record.Topic,
				strconv.FormatInt(int64(record.Partition), 10),
				strconv.FormatInt(record.Offset, 10), tConsume, eventID}
			for _, name := range copied {
				event = append(event, pythonCell(fields[name]))
			}
			if err := consumerTable.writer.Write(row); err != nil {
				fmt.Fprintln(os.Stderr, "franz-consumer:", err)
				status = 1
				break poll
			}
			if err := eventsTable.writer.Write(event); err != nil {
				fmt.Fprintln(os.Stderr, "franz-consumer:", err)
				status = 1
				break poll
			}
			written++
			if written%flushEvery == 0 {
				consumerTable.writer.Flush()
				eventsTable.writer.Flush()
			}
		}
	}
	if status == 0 && !listed {
		// 23 Oct 2026: never assigned, the list is written still, while the client's threads
		// are alive, so that the run's record holds it.
		if err := writeThreads(*threadsOut); err != nil {
			fmt.Fprintln(os.Stderr, "franz-consumer:", err)
			status = 1
		}
	}
	for _, t := range []*table{consumerTable, eventsTable} {
		if err := t.close(); err != nil {
			fmt.Fprintln(os.Stderr, "franz-consumer:", err)
			status = 1
		}
	}
	client.Close()
	if status != 0 {
		return status
	}
	fmt.Printf("OK franz-go consumer: wrote %d rows -> %s\n", written, *out)
	fmt.Printf("OK franz-go consumer: wrote %d rows -> %s\n", written, eventsPath)
	return 0
}

// table is one CSV file, written as Python's csv module writes one: every row ends in \r\n.
type table struct {
	file   *os.File
	writer *csv.Writer
}

// create opens a table at path and writes its header.
func create(path string, header []string) (*table, error) {
	file, err := os.Create(path)
	if err != nil {
		return nil, err
	}
	writer := csv.NewWriter(file)
	writer.UseCRLF = true
	if err := writer.Write(header); err != nil {
		file.Close()
		return nil, err
	}
	return &table{file: file, writer: writer}, nil
}

// close writes out what the table holds and closes its file.
func (t *table) close() error {
	t.writer.Flush()
	if err := t.writer.Error(); err != nil {
		t.file.Close()
		return err
	}
	return t.file.Close()
}

// beside is the event log's path: consumer.csv -> consumer_events.csv in the same directory, as
// kafka_consumer.py names it with Path.with_name.
func beside(out string) string {
	name := filepath.Base(out)
	return filepath.Join(filepath.Dir(out),
		strings.TrimSuffix(name, filepath.Ext(name))+"_events.csv")
}

// text is a JSON string field's value; ok is false where the field is absent or not a string.
func text(raw json.RawMessage) (string, bool) {
	var value string
	if len(raw) == 0 || raw[0] != '"' || json.Unmarshal(raw, &value) != nil {
		return "", false
	}
	return value, true
}

// pythonCell is one field of the message as kafka_consumer.py writes it. Its csv writer is handed
// what json.loads made of the field, so a string is written as itself, true and false as True and
// False, null or an absent field as an empty cell, and a number as the text it came as, which is
// what Python prints back for the numbers the producers send: an integer's digits, a float's
// shortest form.
func pythonCell(raw json.RawMessage) string {
	switch string(raw) {
	case "", "null":
		return ""
	case "true":
		return "True"
	case "false":
		return "False"
	}
	if value, ok := text(raw); ok {
		return value
	}
	return string(raw)
}

// clockResolutionNs is the smallest step the wall clock takes over samples reads, or 0 where it
// never moved.
func clockResolutionNs(samples int) int64 {
	var finest int64
	previous := time.Now().UnixNano()
	for i := 0; i < samples; i++ {
		current := time.Now().UnixNano()
		if step := current - previous; step > 0 && (finest == 0 || step < finest) {
			finest = step
		}
		previous = current
	}
	return finest
}

// moduleVersion is the version of the module at path that this binary was built with, from the
// binary's own build record.
func moduleVersion(path string) string {
	info, ok := debug.ReadBuildInfo()
	if !ok {
		return "unknown"
	}
	for _, module := range info.Deps {
		if module.Path == path {
			return module.Version
		}
	}
	return "unknown"
}

// writeThreads writes every OS thread the kernel lists for this process to path, by way of a file
// beside it, so that the kit, which waits for the file, never reads half a list. Go's runtime
// names no thread, so each one's name is the program's own, and no row has a role or a runtime
// name: no OS thread is the fetching one. Where the kernel lists no threads, the file holds its
// header alone and the reason is in the log.
func writeThreads(path string) error {
	rows := [][]string{threadColumns}
	ids, err := taskIDs(tasks)
	if err != nil {
		fmt.Fprintf(os.Stderr, "franz-consumer: no thread list to read (%v); %s holds its header "+
			"alone\n", err, path)
	}
	for _, id := range ids {
		name, err := os.ReadFile(filepath.Join(tasks, strconv.Itoa(id), "comm"))
		if err != nil {
			continue // the thread ended between the listing and this read
		}
		rows = append(rows, []string{strconv.Itoa(id), strings.TrimSuffix(string(name), "\n"),
			"", ""})
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	partial := path + ".tmp"
	file, err := os.Create(partial)
	if err != nil {
		return err
	}
	if err := csv.NewWriter(file).WriteAll(rows); err != nil {
		file.Close()
		return err
	}
	if err := file.Close(); err != nil {
		return err
	}
	if err := os.Rename(partial, path); err != nil {
		return err
	}
	fmt.Printf("OK threads: %d listed -> %s\n", len(rows)-1, path)
	return nil
}

// taskIDs is the kernel's ids for this process's threads, in order.
func taskIDs(dir string) ([]int, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, err
	}
	ids := make([]int, 0, len(entries))
	for _, entry := range entries {
		if id, err := strconv.Atoi(entry.Name()); err == nil {
			ids = append(ids, id)
		}
	}
	sort.Ints(ids)
	return ids, nil
}
