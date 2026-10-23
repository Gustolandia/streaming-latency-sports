# The franz-go consumer

This is a Kafka consumer built on franz-go, the Go library that Redpanda's kgo-repeater (one of
the audited tools) is built on. It writes the same files as `scripts/kafka_consumer.py`, so that
the reader and the integrity rule cannot tell which consumer made a run.

**Words used here.** Each part below repeats the ones it uses.

- **Consumer**: the program that receives messages from Kafka.
- **Broker**: the Kafka server that holds the messages.
- **Fetch**: the consumer's request to the broker for the next messages.
- **Poll**: the call the program makes to get messages from its client library.
- **Offset**: a message's number in its partition, given by the broker.
- **OS thread**: a line of work the operating system schedules; what `chrt` gives a policy to.
- **Goroutine**: Go's own small line of work. Go runs many goroutines on a few OS threads, and
  moves them from thread to thread as it likes.
- **Toolchain**: the Go compiler and its tools, at one version.
- **ns, µs, ms**: nanosecond; microsecond, 1,000 ns; millisecond, 1,000 µs.

## Why it exists

*Words in this part.* **Consumer**: the receiving program. **Fetch**: its request for the next
messages. **Toolchain**: the compiler, at one version.

Block U (`docs/results/under_load/README.md`) confirmed it for kafka-python: a consumer that
fetches its own messages lets its own thread's delays into the measured latency, through its next
request. None of the measuring tools the paper audits uses kafka-python. kgo-repeater uses
franz-go. This consumer runs franz-go the way a program normally runs it, so that the next block
can time it from the packet captures on the client machine without changing it.

It is built on the same library and by the same compiler as kgo-repeater at the commit
`cloud/azure/tools.sh` pins (kgo-verifier 6567f2f5, whose `go.mod` requires franz-go v1.19.5 and
names toolchain go1.23.11).

## What it writes

*Words in this part.* **Wall clock**: the machine's clock of the date and time, the one every
client stamps with. **ns, µs**: nanosecond, and microsecond (1,000 ns).

The two files, with the columns of `scripts/kafka_consumer.py`:

    consumer.csv         run_id, backend, topic, event_id, match_id, t_sim_seconds,
                         t_cons_recv_ns, t_output_ns
    consumer_events.csv  run_id, backend, topic, partition, offset, t_consume_ns, event_id,
                         match_id, t_sim_seconds, t_emit_offset_s, t_emit_planned_ns, s3_uid,
                         s3_rev, s3_is_correction

`consumer_events.csv` is the output's sibling (`consumer.csv` gives `consumer_events.csv`).

- `t_consume_ns` is `time.Now().UnixNano()`, taken when the program has the message from
  `PollFetches`. `t_cons_recv_ns` is the same reading, and `t_output_ns` the next one.
- That clock is CLOCK_REALTIME, the clock of Python's `time.time_ns()` and Java's
  `Instant.now()`. On x86-64 Linux, Go's `time.now` (`runtime/time_linux_amd64.s`) asks the
  kernel's `clock_gettime` for clock 0, CLOCK_REALTIME, and for clock 1, CLOCK_MONOTONIC, for the
  part that only measures intervals. On arm64 Linux, `time_now` (`runtime/timestub.go`) calls
  `walltime`, which loads CLOCK_REALTIME (`runtime/sys_linux_arm64.s`). Read in the go1.23.11
  sources.
- Each value is written as `kafka_consumer.py`'s CSV writer writes it: `True` and `False` for
  true and false, an empty cell for null or a missing field, a number as the text it came as.
  Every row ends in `\r\n`, as Python's `csv` module ends them.
- Before it connects, it measures its own clock and refuses one that steps coarser than 25 µs,
  the bar `scripts/law_clock.py` and `harness/java`'s `LawClock` hold. Its `CONFIG` line names
  the franz-go version, read from the binary's own build record, and the Go version.
- It ends with `OK franz-go consumer: wrote N rows -> PATH`, once for each file.

## How a message is identified

*Words in this part.* **Offset**: a message's number in its partition, given by the broker.

By the partition and offset franz-go hands back with it (`Record.Partition`, `Record.Offset`),
written in `consumer_events.csv`. The payload's `run_id` only decides whether a message is this
run's, and its `event_id` is only copied into its column.

## Which goroutine fetches, and what waits at the broker

*Words in this part.* **Fetch**: the request for the next messages. **Poll**: the program's call
for messages. **Goroutine**: Go's small line of work, moved between OS threads by Go itself.
**OS thread**: what the operating system schedules, and what `chrt` sets.

In franz-go v1.19.5 (`pkg/kgo`):

- For each broker it reads from, the client keeps a **source**, and the source's goroutine
  (`source.loopFetch`, `source.go`) decides when to fetch. The source keeps one fetch's answer
  waiting for the program, and sends the next fetch as soon as the program takes that answer,
  which `PollFetches` does (`takeBuffered`). In the code's own words, the source "aims to have
  *one* buffered fetch at all times".
- The request is written to the socket by the broker connection's request goroutine
  (`handleReqs`, `broker.go`), and its answer is read by the connection's response goroutine
  (`handleResps`). Fetches have a connection of their own (`cxnFetch`). Each of the two
  goroutines starts when its queue gains an entry and ends when the queue is empty again.
- So, while the program works on what one poll gave it, one fetch waits at the broker: the one
  sent as the program took the last answer. A message that reaches the broker then is sent at
  once. When that answer is in, no further fetch leaves until the program polls again, and a
  message that reaches the broker after it waits there for the program's next `PollFetches`.
  That is the pattern of kafka-python and of Kafka's Java consumer, with the request sent by
  another goroutine rather than by the polling one.
- franz-go's defaults stand: a broker holds a fetch up to 5 s (`FetchMaxWait`) and answers as
  soon as there is any data; one fetch in flight or waiting per broker (`MaxConcurrentFetches`);
  offsets committed every 5 s. The group protocol is the classic one: v1.19.x offers the newer
  protocol only to a program that opts in through a special context key (its `CHANGELOG.md`).

**Can the fetch have an OS thread of its own?** Not without changing franz-go.
`runtime.LockOSThread` ties the goroutine that calls it to the OS thread it is on, and only that
goroutine can call it; the fetching goroutines are franz-go's own. The two that touch the socket
end whenever their queue empties, and a goroutine that ends while tied takes its OS thread with
it: Go ends that thread. So even a call to `LockOSThread` from one of franz-go's hooks, which
run on the goroutine that wrote or read, would leave no lasting thread to give a policy to. The
kit can give a policy only to all of the process's threads at once, with `chrt -a -f -p 80 <pid>`
or by starting the program under `chrt -f 80`, whose threads then inherit it; that also raises
the program's own goroutines.

## The thread list (`--threads-out`)

*Words in this part.* **OS thread**: what the operating system schedules. **Goroutine**: Go's own
small line of work, which no OS thread keeps.

With `--threads-out PATH`, once the group has assigned the partitions (`OnPartitionsAssigned`),
or at the end if it never did, the consumer writes every OS thread of the process. The columns
are those of the other two consumers that take the flag (`scripts/kafka_consumer_confluent.py`
and `harness/java`'s `LawConsumer`):

    tid           the kernel's id for the thread
    name          the kernel's name for it, at most 15 bytes
    role          empty here
    runtime_name  empty here

Go names no thread, so the kernel names every one after the program (`franz-consumer`), and no
row has a role, because no OS thread is the fetching one. The list is written beside the path and
then moved onto it, so a reader never sees half of it.

## Flags

| Flag | Default | What it sets |
|---|---|---|
| `--bootstrap` | `localhost:9092` | the brokers to start from, `host:port[,host:port]` |
| `--topic` | `sb-events` | the topic |
| `--group` | `sb-consumer-<run-id>` | the consumer group, one of its own |
| `--run-id` | (required) | this run's id; messages of other runs are skipped |
| `--out` | (required) | `consumer.csv`; `consumer_events.csv` goes beside it |
| `--idle-seconds` | `15` | stop after this long with no message of this run |
| `--threads-out` | (off) | the thread list above |

Go's flag reader takes `--name value` and `-name value` alike.

## Building on the driver

*Words in this part.* **Toolchain**: the Go compiler and tools at one version. **Module**: a Go
library at one version. **go.sum**: the list of checksums a build must match.

How `cloud/azure/tools.sh` installs Go for the audited Go tools:

- `get_go` uses a `go` already on the PATH or at `/usr/local/go`, and otherwise fetches Go 1.22.5
  from go.dev and unpacks it at `/usr/local/go` (`GO_VERSION`, pinned "because the compiler is
  part of what produced the binary").
- The tools pinned by module are built with `go install module@version` (`go_tool`). The four of
  freeze 35 are cloned at their commit and built as their own repositories build them
  (`go_source_build`); kgo-repeater is `CGO_ENABLED=0 go build -o kgo-repeater
  cmd/kgo-repeater/main.go`, in kgo-verifier at 6567f2f5.
- Go fetches the toolchain a module's `go.mod` asks for when it is newer than the one installed,
  so tools.sh writes `go version`, run inside each module, beside its commit.

This consumer is built on the driver, once `get_go` has run, with:

    bash harness/go/build.sh

which:

1. puts `/usr/local/go/bin` on the PATH if `go` is not on it;
2. sets `GOTOOLCHAIN=go1.23.11`, so the go command fetches exactly that toolchain from the module
   proxy, checked against the checksum database, whatever Go is installed; `GOFLAGS=-mod=readonly`,
   so a module that `go.sum` does not vouch for stops the build; and `CGO_ENABLED=0`, a static
   binary, as tools.sh builds the Go tools;
3. runs `go vet .` and then `go build -o out/franz-consumer .`;
4. checks, with `go version -m`, that the binary was built by go1.23.11 on franz-go v1.19.5,
   keeps that record in `out/BUILD_INFO.txt`, and writes the binary's SHA-256 to `out/SHA256SUM`.

| Pinned | Version | Where the version comes from |
|---|---|---|
| github.com/twmb/franz-go | v1.19.5 | kgo-verifier 6567f2f5's `go.mod` |
| github.com/twmb/franz-go/pkg/kmsg | v1.11.2 | franz-go v1.19.5's `go.mod` |
| github.com/klauspost/compress | v1.18.0 | franz-go v1.19.5's `go.mod` |
| github.com/pierrec/lz4/v4 | v4.1.22 | franz-go v1.19.5's `go.mod` |
| golang.org/x/crypto | v0.38.0 | franz-go v1.19.5's `go.mod`; in `go.sum` for the module graph, no package of it is built |
| toolchain | go1.23.11 | kgo-verifier 6567f2f5's `go.mod` |

The checksums in `go.sum` are the Go checksum database's (sum.golang.org), and kgo-verifier's
`go.sum` at 6567f2f5 holds the same lines. The module's `go` line, 1.23.8, is the least franz-go
v1.19.5 accepts. `out/` is not committed.

The kit runs it as:

    harness/go/out/franz-consumer --run-id <id> --out runs/<id>/consumer.csv \
        --bootstrap <host:port> --topic <topic> --idle-seconds <n> \
        [--threads-out runs/<id>/consumer_tids.csv]

## Checked without a Go toolchain

*Words in this part.* **CI**: the tests run on every push, on machines with no Go installed.

`tests/unit/test_go_and_java_consumers.py` reads `main.go`, `go.mod`, `go.sum` and `build.sh`
and holds them to the interface: the flags, the columns against `kafka_consumer.py`'s, the
stamps, the partition and offset, the pins, every import used, and a `go.sum` line for every
module `go.mod` names. It does for this consumer what
`tests/unit/test_two_clients_write_the_same_files.py` does for the Java one: source checks,
because CI has no Go toolchain and no test in the suite may skip. The compiler's own check is
`build.sh`'s `go vet` and `go build`, on the driver.
