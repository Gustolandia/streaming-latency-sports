// Command natsgo-consumer is a NATS JetStream consumer on nats.go (github.com/nats-io/nats.go and
// its jetstream package) that writes the files scripts/nats_consumer.py writes, so that the reader
// and the integrity rule cannot tell which client produced a run.
//
// It makes sure of the stream and of the durable pull consumer nats_consumer.py makes, and reads
// the consumer with Consume, nats.go's own way of keeping pull requests waiting at the server. It
// writes no message whose run_id is not this run's, and stops after --idle-seconds with no
// message. Each message is identified as the server identifies it, by the stream sequence nats.go
// reads from the message's own metadata (Msg.Metadata); the payload's event_id is only copied
// into its column.
//
// The stamps are nats_consumer.py's. t_consume_ns is time.Now().UnixNano(), the wall clock, which
// Go reads with clock_gettime(CLOCK_REALTIME) on Linux (time.now in runtime/time_linux_amd64.s on
// x86-64, walltime in runtime/sys_linux_arm64.s on arm64), taken as the handler Consume calls
// begins; t_cons_recv_ns is the same reading, and t_output_ns the one taken once the message is
// found to be this run's.
//
// nats.go keeps the requests waiting by itself (Consume, jetstream/pull.go, v1.54.0). It asks for
// --max-messages messages in one request and, each time the handler has returned and fewer than
// --threshold of the messages it asked for are still due, asks for the difference, so that the
// server holds a request for messages while the handler works. The connection's reading goroutine
// (readLoop, nats.go) reads the socket, the subscription's goroutine (waitForMsgs) calls the
// handler, and the flusher goroutine (flusher) writes the requests and the acknowledgments to the
// socket. Go's scheduler runs goroutines on whichever of the process's OS threads is free, and
// nats.go names none of them, so no OS thread is the receiving thread; README.md says what that
// leaves the kit.
//
// --threads-out writes, once Consume has asked for its first messages, each of the process's OS
// threads with the kernel's name for it, which for every one is the program's own.
package main

import (
	"context"
	"encoding/csv"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"runtime"
	"runtime/debug"
	"slices"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode"

	"github.com/nats-io/nats.go"
	"github.com/nats-io/nats.go/jetstream"
)

// consumerColumns and eventColumns are consumer.csv's and consumer_events.csv's columns, as
// scripts/nats_consumer.py writes them.
var consumerColumns = []string{"run_id", "backend", "stream", "event_id", "match_id",
	"t_sim_seconds", "t_cons_recv_ns", "t_output_ns", "stream_seq"}

var eventColumns = []string{"run_id", "backend", "stream", "stream_seq", "t_consume_ns",
	"event_id", "match_id", "t_sim_seconds", "t_emit_offset_s", "t_emit_planned_ns", "s3_uid",
	"s3_rev", "s3_is_correction"}

// copied are the message's fields the event log copies after its event_id, in its order.
var copied = []string{"match_id", "t_sim_seconds", "t_emit_offset_s", "t_emit_planned_ns",
	"s3_uid", "s3_rev", "s3_is_correction"}

// threadColumns are --threads-out's columns, the same in harness/go,
// scripts/kafka_consumer_confluent.py and harness/java/src/LawConsumer.java.
var threadColumns = []string{"tid", "name", "role", "runtime_name"}

const (
	// tasks is where the kernel lists this process's threads: one directory per thread id, each
	// with the thread's name in comm.
	tasks = "/proc/self/task"

	// clientName is the name the connection gives the server in its CONNECT, beside the
	// sbl-nats-consumer of nats_consumer.py's receive connection.
	clientName = "sbl-natsgo-consumer"

	// maxWaiting and maxAckPending are the durable consumer's limits, MAX_WAITING and
	// MAX_ACK_PENDING in scripts/nats_wire.py, so that the server holds the consumer
	// nats_consumer.py makes: up to 512 requests waiting, and more messages unacknowledged than any
	// run sends, so that delivery never waits on an acknowledgment still on its way.
	maxWaiting    = 512
	maxAckPending = 1000000

	// setupWait bounds the requests that make the stream and the consumer: 10 s, what
	// nats_wire.py gives each answer (40 waits of 0.25 s).
	setupWait = 10 * time.Second

	// idleCheck is how often the idle time is looked at: as often as nats_consumer.py looks at its
	// clock when no frame comes (nats_wire.WAIT_S).
	idleCheck = 250 * time.Millisecond

	// flushEvery is how many messages go between flushes of the two files, as in
	// nats_consumer.py.
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
	flags := flag.NewFlagSet("natsgo-consumer", flag.ContinueOnError)
	runID := flags.String("run-id", "",
		"this run's id; a message whose run_id differs is acknowledged and not written (required)")
	out := flags.String("out", "", "consumer.csv; consumer_events.csv is written beside it (required)")
	streamName := flags.String("stream", "SBL_EVENTS", "the stream")
	subjectName := flags.String("subject", "",
		"the subject the stream takes, if this client creates it (default sbl.<stream>)")
	durableName := flags.String("durable", "", "the durable consumer's name (default sbl-<run id>)")
	host := flags.String("host", "localhost", "the server's host")
	port := flags.Int("port", 4222, "the server's port for clients")
	storage := flags.String("storage", "file",
		"where the stream keeps its messages, if this client creates it: file or memory")
	idleSeconds := flags.Int("idle-seconds", 15, "stop after this many seconds with no message")
	maxMessages := flags.Int("max-messages", jetstream.DefaultMaxMessages,
		"how many messages Consume asks for (jetstream.PullMaxMessages)")
	threshold := flags.Int("threshold", 0,
		"Consume asks for more once fewer than this many are still due "+
			"(jetstream.PullThresholdMessages); 0 leaves nats.go's own, half of --max-messages "+
			"rounded up")
	threadsOut := flags.String("threads-out", "",
		"once Consume has asked for messages, write this process's threads to this CSV")
	probeMs := flags.Int("probe-ms", 100,
		"send a PING on the connection this often, in ms, as nats_consumer.py does; 0 keeps "+
			"nats.go's own interval, two minutes")
	if err := flags.Parse(argv); err != nil {
		return 2
	}
	if *runID == "" || *out == "" {
		fmt.Fprintln(os.Stderr, "natsgo-consumer: --run-id and --out are required")
		return 2
	}
	kept := jetstream.FileStorage
	switch *storage {
	case "file":
	case "memory":
		kept = jetstream.MemoryStorage
	default:
		fmt.Fprintf(os.Stderr, "natsgo-consumer: --storage is file or memory, not %q\n", *storage)
		return 2
	}
	if *probeMs < 0 {
		fmt.Fprintln(os.Stderr, "natsgo-consumer: --probe-ms is at least 0")
		return 2
	}
	if *maxMessages < 1 || *threshold < 0 {
		fmt.Fprintln(os.Stderr,
			"natsgo-consumer: --max-messages is at least 1 and --threshold at least 0")
		return 2
	}
	if *threshold == 0 {
		// nats.go's own: half of the messages asked for, rounded up (setDefaults,
		// jetstream/pull.go). It is passed on, so that the value is on record.
		*threshold = (*maxMessages + 1) / 2
	}
	subject := *subjectName
	if subject == "" {
		subject = "sbl." + *streamName
	}
	durable := *durableName
	if durable == "" {
		durable = safeName("sbl-" + *runID)
	}
	for _, refused := range []error{checkedName(*streamName), checkedSubject(subject),
		checkedName(durable)} {
		if refused != nil {
			fmt.Fprintln(os.Stderr, "natsgo-consumer:", refused)
			return 2
		}
	}

	// 23 Oct 2026: every client of the block measures its clock before a run and refuses one
	// that steps coarser than 25 microseconds (scripts/law_clock.py), and which build ran is part
	// of what the block reports.
	resolution := clockResolutionNs(clockSamples)
	if resolution <= 0 || resolution > finestUsableNs {
		fmt.Fprintf(os.Stderr, "STOP_RULE: the nats.go consumer will not run on this clock: it "+
			"steps in %d ns, and this experiment needs better than %d ns.\n",
			resolution, finestUsableNs)
		return 1
	}
	fmt.Printf("CONFIG effective client=nats.go nats_go=%s go=%s clock_resolution_ns=%d\n",
		moduleVersion("github.com/nats-io/nats.go"), runtime.Version(), resolution)

	eventsPath := beside(*out)
	if err := os.MkdirAll(filepath.Dir(*out), 0o755); err != nil {
		fmt.Fprintln(os.Stderr, "natsgo-consumer:", err)
		return 1
	}

	r := &receiver{runID: *runID}
	url := "nats://" + net.JoinHostPort(*host, strconv.Itoa(*port))
	// nats.go's connection options stand. A connection lost in a run ends the run, as it ends
	// nats_consumer.py's, rather than leaving a gap that nats.go would reconnect across; so does
	// any error nats.go reports on its own, such as a slow consumer's dropped messages.
	nc, err := nats.Connect(url, nats.Name(clientName),
		nats.DisconnectErrHandler(func(_ *nats.Conn, err error) {
			r.fail(fmt.Errorf("the connection to %s was lost (%v)", url, err))
		}),
		nats.ErrorHandler(func(_ *nats.Conn, _ *nats.Subscription, err error) {
			r.fail(fmt.Errorf("nats.go reported: %w", err))
		}),
		probing(*probeMs))
	if err != nil {
		fmt.Fprintln(os.Stderr, "natsgo-consumer:", err)
		return 1
	}
	js, err := jetstream.New(nc)
	if err != nil {
		fmt.Fprintln(os.Stderr, "natsgo-consumer:", err)
		nc.Close()
		return 1
	}

	// The stream first, made if it is absent, so that the consumer has one to read whichever
	// client starts first; then the durable consumer, the one nats_consumer.py makes: every
	// message from the first, each acknowledged by itself, sent as fast as it can be.
	ctx, cancel := context.WithTimeout(context.Background(), setupWait)
	defer cancel()
	if err := ensureStream(ctx, js, jetstream.StreamConfig{
		Name:      *streamName,
		Subjects:  []string{subject},
		Retention: jetstream.LimitsPolicy,
		Storage:   kept,
		Replicas:  1,
		Discard:   jetstream.DiscardOld,
	}); err != nil {
		fmt.Fprintln(os.Stderr, "natsgo-consumer:", err)
		nc.Close()
		return 1
	}
	cons, err := js.CreateOrUpdateConsumer(ctx, *streamName, jetstream.ConsumerConfig{
		Durable:       durable,
		DeliverPolicy: jetstream.DeliverAllPolicy,
		AckPolicy:     jetstream.AckExplicitPolicy,
		ReplayPolicy:  jetstream.ReplayInstantPolicy,
		MaxAckPending: maxAckPending,
		MaxWaiting:    maxWaiting,
	})
	if err != nil {
		fmt.Fprintln(os.Stderr, "natsgo-consumer:", err)
		nc.Close()
		return 1
	}

	consumerTable, err := create(*out, consumerColumns)
	if err != nil {
		fmt.Fprintln(os.Stderr, "natsgo-consumer:", err)
		nc.Close()
		return 1
	}
	eventsTable, err := create(eventsPath, eventColumns)
	if err != nil {
		fmt.Fprintln(os.Stderr, "natsgo-consumer:", err)
		consumerTable.close()
		nc.Close()
		return 1
	}
	r.consumer, r.events = consumerTable, eventsTable

	// Manipulation check, as in nats_consumer.py: the pull options Consume is given, the
	// consumer's limits and the names the run has. The expiry is nats.go's, not passed.
	fmt.Printf("CONFIG effective max_messages=%d threshold=%d expires_ms=%d max_waiting=%d "+
		"max_ack_pending=%d storage=%s stream=%s subject=%s durable=%s server_version=%s "+
		"probe_ms=%d\n",
		*maxMessages, *threshold, jetstream.DefaultExpires.Milliseconds(), maxWaiting,
		maxAckPending, *storage, *streamName, subject, durable, nc.ConnectedServerVersion(),
		*probeMs)

	// The idle time counts from here, as nats_consumer.py's counts from its first requests.
	r.lastMessage = time.Now()
	consumeCtx, err := cons.Consume(r.handle,
		jetstream.PullMaxMessages(*maxMessages),
		jetstream.PullThresholdMessages(*threshold),
		jetstream.ConsumeErrHandler(r.reported))
	if err != nil {
		fmt.Fprintln(os.Stderr, "natsgo-consumer:", err)
		r.stop()
		consumerTable.close()
		eventsTable.close()
		nc.Close()
		return 1
	}

	status := 0
	if *threadsOut != "" {
		// Consume has subscribed and asked for its first messages, so the connection's
		// goroutines and the subscription's are running.
		if err := writeThreads(*threadsOut); err != nil {
			fmt.Fprintln(os.Stderr, "natsgo-consumer:", err)
			status = 1
		}
	}
	idle := time.Duration(*idleSeconds) * time.Second
	for status == 0 && !r.over(idle) {
		time.Sleep(idleCheck)
	}
	r.stop()
	consumeCtx.Stop()
	nc.Close()
	// Nothing writes the receiver once it has stopped.
	if r.err != nil {
		fmt.Fprintln(os.Stderr, "natsgo-consumer:", r.err)
		status = 1
	}
	for _, t := range []*table{consumerTable, eventsTable} {
		if err := t.close(); err != nil {
			fmt.Fprintln(os.Stderr, "natsgo-consumer:", err)
			status = 1
		}
	}
	if status != 0 {
		return status
	}
	fmt.Printf("OK nats.go consumer: %d redeliveries not written\n", r.redelivered)
	fmt.Printf("OK nats.go consumer: wrote %d rows -> %s\n", r.written, *out)
	fmt.Printf("OK nats.go consumer: wrote %d rows -> %s\n", r.written, eventsPath)
	return 0
}

// receiver is what the handler Consume calls keeps between messages. Its mutex is held while a
// message is handled, while the main goroutine looks at the idle time or stops the run, and while
// an error is taken, so that none of them crosses another. Once stopping is set, the handler
// writes nothing and no error is taken.
type receiver struct {
	mu          sync.Mutex
	runID       string
	consumer    *table
	events      *table
	written     int
	redelivered int
	lastMessage time.Time
	stopping    bool
	err         error
}

// handle is the handler Consume calls with each message, on the subscription's goroutine. The
// receive stamp is its first reading, before anything else is done with the message.
func (r *receiver) handle(msg jetstream.Msg) {
	received := time.Now()
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.stopping || r.err != nil {
		return
	}
	r.err = r.take(msg, received)
}

// take writes one message's rows, if it is this run's and has not been delivered before, and
// acknowledges it, as nats_consumer.py does: a message of another run, or one delivered again
// after an acknowledgment was lost, is acknowledged and not written.
func (r *receiver) take(msg jetstream.Msg, received time.Time) error {
	meta, err := msg.Metadata()
	if err != nil {
		return err
	}
	// nats.go reads a token that is not a number as 0, and a stream's sequence starts at 1:
	// nats_wire.ack_metadata refuses such a subject, so that a garbled one cannot pass for a
	// message.
	if meta.Sequence.Stream == 0 {
		return fmt.Errorf("the reply subject %q names no stream sequence", msg.Reply())
	}
	seq := strconv.FormatUint(meta.Sequence.Stream, 10)
	fields := map[string]json.RawMessage{}
	if err := json.Unmarshal(msg.Data(), &fields); err != nil {
		return fmt.Errorf("the message at stream sequence %s is not the producer's JSON: %v", seq,
			err)
	}
	id, ok := text(fields["run_id"])
	thisRun := ok && id == r.runID
	if thisRun && meta.NumDelivered > 1 {
		r.redelivered++
	} else if thisRun {
		tConsume := strconv.FormatInt(received.UnixNano(), 10)
		tOutput := strconv.FormatInt(time.Now().UnixNano(), 10)
		eventID := pythonCell(fields["event_id"])
		row := []string{r.runID, "nats", meta.Stream, eventID, pythonCell(fields["match_id"]),
			pythonCell(fields["t_sim_seconds"]), tConsume, tOutput, seq}
		event := []string{r.runID, "nats", meta.Stream, seq, tConsume, eventID}
		for _, name := range copied {
			event = append(event, pythonCell(fields[name]))
		}
		if err := r.consumer.writer.Write(row); err != nil {
			return err
		}
		if err := r.events.writer.Write(event); err != nil {
			return err
		}
		r.written++
		if r.written%flushEvery == 0 {
			r.consumer.writer.Flush()
			r.events.writer.Flush()
		}
	}
	if err := msg.Ack(); err != nil {
		return fmt.Errorf("the acknowledgment of stream sequence %s: %v", seq, err)
	}
	r.lastMessage = time.Now()
	return nil
}

// reported is Consume's error handler. One error it is given is a request that ended without a
// message and that nats.go replaces at once, as nats_consumer.py replaces it: 409 Leadership
// Change, which only a cluster sends (handleStatusMsg counts nothing due, and checkPending asks
// again). It is logged. Any other ends the run, among them a heartbeat missed, a request refused
// and the consumer deleted. A request that expired (408) is taken off the count inside nats.go and
// reported to nobody. 404 No Messages answers a request that asked not to wait, which Consume
// never sends, and nats.go does not count again after one, so its requests could run dry.
func (r *receiver) reported(_ jetstream.ConsumeContext, err error) {
	if errors.Is(err, jetstream.ErrConsumerLeadershipChanged) {
		r.mu.Lock()
		if !r.stopping {
			fmt.Fprintln(os.Stderr, "natsgo-consumer: a request ended without a message, and "+
				"nats.go replaced it:", err)
		}
		r.mu.Unlock()
		return
	}
	r.fail(fmt.Errorf("nats.go's Consume reported: %w", err))
}

// fail ends the run with err, unless it has already failed or is stopping, as it is once the
// connection is closed at the end.
func (r *receiver) fail(err error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if !r.stopping && r.err == nil {
		r.err = err
	}
}

// over is whether the run is to stop, as nats_consumer.py stops: a fault, or --idle-seconds since
// the last message of any run, or since Consume began if none came.
func (r *receiver) over(idle time.Duration) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.err != nil || time.Since(r.lastMessage) >= idle {
		r.stopping = true
	}
	return r.stopping
}

// stop ends the run: from here on the handler writes nothing and no error is taken, so that the
// tables can be closed.
func (r *receiver) stop() {
	r.mu.Lock()
	r.stopping = true
	r.mu.Unlock()
}

// ensureStream makes the stream if it is absent, as nats_wire.ensure_stream does. One that exists
// with another configuration than this request's, as a server may hold for one an older client
// made, is taken if it is kept the same way and takes this subject; otherwise its error stands.
func ensureStream(ctx context.Context, js jetstream.JetStream, want jetstream.StreamConfig) error {
	_, err := js.CreateStream(ctx, want)
	if !errors.Is(err, jetstream.ErrStreamNameAlreadyInUse) {
		return err
	}
	stream, err := js.Stream(ctx, want.Name)
	if err != nil {
		return err
	}
	have := stream.CachedInfo().Config
	if !slices.Contains(have.Subjects, want.Subjects[0]) || have.Storage != want.Storage {
		return fmt.Errorf("stream %s exists on %v with %s storage, not on %s with %s", want.Name,
			have.Subjects, have.Storage, want.Subjects[0], want.Storage)
	}
	return nil
}

// safeName is value with every character but letters, digits, '_' and '-' made '_', as
// nats_wire.safe_name makes it: a name made from a run id that JetStream takes whatever the run
// id holds.
func safeName(value string) string {
	return strings.Map(func(c rune) rune {
		if c == '_' || c == '-' || ('0' <= c && c <= '9') || ('a' <= c && c <= 'z') ||
			('A' <= c && c <= 'Z') {
			return c
		}
		return '_'
	}, value)
}

// checkedName is nil for a stream's or a consumer's name that JetStream takes, as
// nats_wire.checked_name decides: one or more characters, none of them white space, '.', '*',
// '>' or a path separator, and all of them printable.
func checkedName(name string) error {
	if name == "" || strings.ContainsAny(name, ".*>/\\") ||
		strings.IndexFunc(name, pythonSpace) >= 0 ||
		strings.IndexFunc(name, func(c rune) bool { return !unicode.IsPrint(c) }) >= 0 {
		return fmt.Errorf("%q cannot name a stream or a consumer", name)
	}
	return nil
}

// checkedSubject is nil for a subject to publish to, as nats_wire.checked_subject decides: tokens
// divided by single dots, each of one or more characters and none of them white space or a
// wildcard.
func checkedSubject(subject string) error {
	for _, token := range strings.Split(subject, ".") {
		if token == "" || strings.ContainsAny(token, "*>") ||
			strings.IndexFunc(token, pythonSpace) >= 0 {
			return fmt.Errorf("%q is not a subject to publish to", subject)
		}
	}
	return nil
}

// pythonSpace is whether Python's \s, which nats_wire.py's checks use, takes c: what Go's
// unicode.IsSpace takes, and U+001C to U+001F, which Python counts as white space and Go does not.
func pythonSpace(c rune) bool {
	return unicode.IsSpace(c) || (c >= 0x1c && c <= 0x1f)
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
// nats_consumer.py names it with Path.with_name.
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

// pythonCell is one field of the message as nats_consumer.py writes it. Its csv writer is handed
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
// name: no OS thread is the receiving one. Where the kernel lists no threads, the file holds its
// header alone and the reason is in the log.
func writeThreads(path string) error {
	rows := [][]string{threadColumns}
	ids, err := taskIDs(tasks)
	if err != nil {
		fmt.Fprintf(os.Stderr, "natsgo-consumer: no thread list to read (%v); %s holds its header "+
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

// probing is the option that sends a PING on the connection every probeMs, as
// nats_consumer.py's --probe-ms does, so that each run carries probes of the connection's round
// trip for the reader's checks. No limit a stall could reach is set on PINGs left unanswered, so
// that a slow PONG is measured rather than taken for a lost connection. 0 keeps nats.go's own
// interval, two minutes.
func probing(probeMs int) nats.Option {
	if probeMs == 0 {
		return func(*nats.Options) error { return nil }
	}
	return func(o *nats.Options) error {
		o.PingInterval = time.Duration(probeMs) * time.Millisecond
		o.MaxPingsOut = 1 << 20
		return nil
	}
}
