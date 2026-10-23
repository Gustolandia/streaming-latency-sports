# The nats.go consumer

This is a NATS JetStream consumer built on nats.go, the official Go client of NATS. It is the
library the NATS command-line tool is built on, whose `latency` and `bench` commands are two of
the audited tools (nats-latency and nats-bench). It writes the same files as
`scripts/nats_consumer.py`, so that the reader and the integrity rule cannot tell which consumer
made a run.

**Words used here.** Each part below repeats the ones it uses.

- **Consumer**: the program that receives messages from NATS.
- **Server**: nats-server with JetStream on, which holds the messages.
- **Stream**: where JetStream keeps the messages. The server numbers each message in it: its
  **stream sequence**.
- **Durable consumer**: the server's record of what this program has been sent and has
  acknowledged.
- **Pull request**: the program's request to the server for up to a number of messages. It waits
  at the server until that many have been sent, or until it expires.
- **Acknowledgment**: the program's word to the server that it has a message.
- **OS thread**: a line of work the operating system schedules; what `chrt` gives a policy to.
- **Goroutine**: Go's own small line of work. Go runs many goroutines on a few OS threads, and
  moves them from thread to thread as it likes.
- **Toolchain**: the Go compiler and its tools, at one version.
- **ns, µs, ms**: nanosecond; microsecond, 1,000 ns; millisecond, 1,000 µs.

## Why it exists

*Words in this part.* **Pull request**: the request for the next messages, which waits at the
server. **Toolchain**: the compiler, at one version.

Block U (`docs/results/under_load/README.md`) confirmed it for kafka-python: a consumer that
fetches its own messages lets its own thread's delays into the measured latency, through its next
request. A server that can keep requests waiting takes the thread back out, and block N tests
that for NATS. `scripts/nats_consumer.py` keeps its requests waiting by hand (`--depth`). nats.go
keeps them waiting by itself, in `Consume`, its way of receiving messages without end. This
consumer runs `Consume` the way a program normally runs it, with nats.go's own pull options, so
that the block can show the same in a client people use, timed from the packet captures on the
client machine without changing it.

## What it writes

*Words in this part.* **Wall clock**: the machine's clock of the date and time, the one every
client stamps with. **Stream sequence**: the server's number for a message. **ns, µs**:
nanosecond, and microsecond (1,000 ns).

The two files, with the columns of `scripts/nats_consumer.py`:

    consumer.csv         run_id, backend, stream, event_id, match_id, t_sim_seconds,
                         t_cons_recv_ns, t_output_ns, stream_seq
    consumer_events.csv  run_id, backend, stream, stream_seq, t_consume_ns, event_id, match_id,
                         t_sim_seconds, t_emit_offset_s, t_emit_planned_ns, s3_uid, s3_rev,
                         s3_is_correction

`consumer_events.csv` is the output's sibling (`consumer.csv` gives `consumer_events.csv`).
`backend` is `nats`, and `stream` is the stream the message's metadata names.

- `t_consume_ns` is `time.Now().UnixNano()`, taken as the handler `Consume` calls begins, before
  anything else is done with the message. `t_cons_recv_ns` is the same reading, and `t_output_ns`
  the one taken once the message has been read and found to be this run's, as in
  `nats_consumer.py`.
- That clock is CLOCK_REALTIME, the clock of Python's `time.time_ns()`. On x86-64 Linux, Go's
  `time.now` (`runtime/time_linux_amd64.s`) asks the kernel's `clock_gettime` for clock 0,
  CLOCK_REALTIME, and for clock 1, CLOCK_MONOTONIC, for the part that only measures intervals.
  On arm64 Linux, `time_now` (`runtime/timestub.go`) calls `walltime`, which loads CLOCK_REALTIME
  (`runtime/sys_linux_arm64.s`). Read in the go1.26.0 sources.
- Each value is written as `nats_consumer.py`'s CSV writer writes it: `True` and `False` for true
  and false, an empty cell for null or a missing field, a number as the text it came as. Every
  row ends in `\r\n`, as Python's `csv` module ends them.
- A message of another run is acknowledged and not written. So is a message delivered a second
  time (its metadata's delivery count above 1), as `nats_consumer.py` does.
- Before it connects, it measures its own clock and refuses one that steps coarser than 25 µs,
  the bar `scripts/law_clock.py` holds. Its first `CONFIG` line names the nats.go version, read
  from the binary's own build record, and the Go version. Its second names the pull options it
  gave `Consume`, nats.go's expiry, the durable consumer's limits, the storage, the names and the
  server's version.
- It ends with `OK nats.go consumer: N redeliveries not written`, then
  `OK nats.go consumer: wrote N rows -> PATH` once for each file.

It writes no `consumer_readtrace.csv`, because the reads of the socket are nats.go's and the
program never sees them.

## How a message is identified

*Words in this part.* **Stream sequence**: the server's number for a message in its stream.

By its stream sequence, from the message's own metadata: `Msg.Metadata()`, which nats.go reads
from the reply subject the server gives each message it delivers,
`$JS.ACK.<stream>.<consumer>.<deliveries>.<stream sequence>...` (`jetstream/message.go` and
`internal/parser`). That is the subject `nats_wire.ack_metadata` reads, and the stream sequence is
written in both files as `stream_seq`. nats.go reads a token that is not a number as 0, and a
stream's sequence starts at 1, so a message whose metadata gives 0 ends the run, as
`nats_wire.ack_metadata` refuses such a subject.

The payload's `run_id` only decides whether a message is this run's, and its `event_id` and the
producer's other fields are only copied into their columns. No request, acknowledgment or stamp
depends on the payload.

## What Consume keeps waiting at the server

*Words in this part.* **Pull request**: a request for up to a number of messages, which waits at
the server. **Goroutine**: Go's small line of work.

In nats.go v1.54.0 (`jetstream/pull.go`), with no pull options given, `Consume`:

- asks for 500 messages in one pull request (`DefaultMaxMessages`). Each request expires after
  30 s (`DefaultExpires`) and asks the server for a heartbeat every 15 s, half the expiry, while
  it waits with nothing to send (`setDefaults`);
- counts the messages still due from its requests: 500 once a request goes out, one fewer each
  time the handler returns (`decrementPendingMsgs`), and fewer by the number an expired request
  still had due, which the server's 408 status gives (`handleStatusMsg`);
- when fewer than 250 are due, half of 500 rounded up (`setDefaults`), asks for the difference to
  500 and counts 500 again (`checkPending`). A goroutine of `Consume`'s own (`pullMessages`)
  hands each such request to the connection, one at a time (`fetchInProgress`).

This consumer passes `--max-messages` to `jetstream.PullMaxMessages` and `--threshold` to
`jetstream.PullThresholdMessages`, so that the two values are on record in its `CONFIG` line.
Their defaults are nats.go's: 500, and half of `--max-messages` rounded up. It passes no other
pull option, so the expiry, the heartbeat and the rest are nats.go's. It also gives `Consume` an
error handler (`jetstream.ConsumeErrHandler`), which sends no request (see "When a run fails").

So while the handler works, the server holds requests for messages. A message that reaches the
server finds one waiting unless 250 or more of the messages the server has sent are ones the
handler has not yet returned from: at 2,000 messages a second, a lag of at least 125 ms. At that
rate a request is used up within a quarter of a second and never expires. One that does expire,
at a low rate, comes off the count when its 408 arrives, and a new request follows if that leaves
fewer than 250 due; until the new one reaches the server, only the requests still waiting there
can take a message, as in `nats_consumer.py`'s one write.

Two differences from `nats_consumer.py` matter to a reader of the captures:

- **Every request of one `Consume` names the same reply subject**, the subscription's inbox
  (`pull`), so a delivered message does not say which request it answered. Whether a request was
  waiting when a message reached the server is a count: the messages asked for by the requests
  that had reached it, less the messages it had sent for them, less those that 408 statuses said
  were still due when their requests expired. Each request's payload gives its count:
  `{"expires":30000000000,"batch":N,"idle_heartbeat":15000000000}`.
- **One connection carries everything**: the requests that make the stream and the consumer, the
  pull requests, the messages, the acknowledgments, and the server's heartbeats (status 100) and
  expiries (status 408). Its CONNECT names it `sbl-natsgo-consumer`, with `"lang":"go"`.

## Which goroutine does what

*Words in this part.* **Goroutine**: Go's small line of work, which no OS thread keeps. **OS
thread**: what the operating system schedules, and what `chrt` sets.

In nats.go v1.54.0 (`nats.go`, `jetstream/pull.go`):

- The connection's reading goroutine (`readLoop`) reads the socket and puts each message on its
  subscription's queue (`processMsg`).
- The subscription's goroutine (`waitForMsgs`) takes each message off the queue and calls
  `Consume`'s handler, which calls this program's. When that returns, it counts the message and
  decides whether to ask for more (`checkPending`).
- `Consume`'s goroutine (`pullMessages`) puts each further request in the connection's buffer,
  and the connection's flusher goroutine (`flusher`) writes the buffer to the socket. The
  acknowledgments go the same way (`publish` wakes the flusher).

Go's scheduler runs these goroutines on whichever of the process's OS threads is free, and nats.go
names none of them.

**Can the receiving goroutine have an OS thread of its own?** Not without changing nats.go.
`runtime.LockOSThread` ties the goroutine that calls it to the OS thread it is on, and only that
goroutine can call it. The reading and flushing goroutines run none of this program's code, so
nothing here can tie them. The subscription's goroutine runs the handler and lasts as long as the
subscription, so the handler could tie it; this consumer does not, because it runs nats.go as
programs normally run it, and the socket is read and written by the other two. The kit can give a
policy only to all of the process's threads at once, with `chrt -a -f -p 80 <pid>` or by starting
the program under `chrt -f 80`, whose threads then inherit it.

## When a run fails

*Words in this part.* **Pull request**: the request for the next messages. **Stream sequence**:
the server's number for a message.

- A connection lost during the run ends it, as it ends `nats_consumer.py`'s, rather than leaving a
  gap that nats.go would reconnect across (`nats.DisconnectErrHandler`).
- An error nats.go reports on its own, such as a slow consumer's dropped messages, ends it
  (`nats.ErrorHandler`).
- Of the errors `Consume` reports, one is a request that ended without a message and that nats.go
  replaces at once, as `nats_consumer.py` replaces it: 409 Leadership Change, which only a
  cluster sends. It is logged. Any other ends the run, among them a heartbeat missed, a request
  refused and the consumer deleted. A request that expired (408) is taken off the count inside
  nats.go and reported to nobody. 404 No Messages, which `nats_consumer.py` survives, ends this
  one: it answers a request that asked not to wait, which `Consume` never sends, and nats.go
  does not count again after one (`handleStatusMsg`), so its requests could run dry.
- A message whose payload is not the producer's JSON, or whose metadata gives no stream sequence,
  ends it, as in `nats_consumer.py`.

The program then exits 1 with no `OK` lines.

## The thread list (`--threads-out`)

*Words in this part.* **OS thread**: what the operating system schedules. **Goroutine**: Go's own
small line of work, which no OS thread keeps.

With `--threads-out PATH`, once `Consume` has subscribed and asked for its first messages, the
consumer writes every OS thread of the process. The columns are those of harness/go's consumer
and the other two that take the flag (`scripts/kafka_consumer_confluent.py` and harness/java's
`LawConsumer`):

    tid           the kernel's id for the thread
    name          the kernel's name for it, at most 15 bytes
    role          empty here
    runtime_name  empty here

Go names no thread, so the kernel names every one after the program (`natsgo-consumer`, 15
bytes), and no row has a role, because no OS thread is the receiving one. What the list can
record is the process's threads at that moment; Go may start more later. The list is written
beside the path and then moved onto it, so a reader never sees half of it.

## Flags

*Words in this part.* **Durable consumer**: the server's record of what this program has been
sent. **Stream**: where the server keeps the messages.

| Flag | Default | What it sets |
|---|---|---|
| `--run-id` | (required) | this run's id; messages of other runs are acknowledged and not written |
| `--out` | (required) | `consumer.csv`; `consumer_events.csv` goes beside it |
| `--host` | `localhost` | the server's host |
| `--port` | `4222` | the server's port for clients |
| `--stream` | `SBL_EVENTS` | the stream |
| `--subject` | `sbl.<stream>` | the subject the stream takes, if this client creates it |
| `--durable` | `sbl-<run id>` | the durable consumer; in the default, the run id's characters other than letters, digits, `_` and `-` become `_` |
| `--storage` | `file` | where the stream keeps its messages, if this client creates it: `file` or `memory` (block N's) |
| `--idle-seconds` | `15` | stop after this many whole seconds with no message |
| `--max-messages` | `500` | `jetstream.PullMaxMessages` |
| `--threshold` | half of `--max-messages`, rounded up | `jetstream.PullThresholdMessages` |
| `--threads-out` | (off) | the thread list above |

The first nine are `nats_consumer.py`'s, with its defaults and its checks on names and subjects.
It does not take that consumer's `--depth`, `--expires-s`, `--one-reply-reads`,
`--delete-stream` or `--thread-record`, nor the flags of the socket-timestamp shim and the
collector switch: the requests, the reads and the threads are nats.go's here. Go's flag reader
takes `--name value` and `-name value` alike.

## Building on the driver

*Words in this part.* **Toolchain**: the Go compiler and tools at one version. **Module**: a Go
library at one version. **go.sum**: the list of checksums a build must match.

This consumer is built on the driver, once `get_go` in `cloud/azure/tools.sh` has run, with:

    bash harness/go-nats/build.sh

which, as `harness/go/build.sh` does:

1. puts `/usr/local/go/bin` on the PATH if `go` is not on it;
2. sets `GOTOOLCHAIN=go1.26.0`, so the go command fetches exactly that toolchain from the module
   proxy, checked against the checksum database, whatever Go is installed; `GOFLAGS=-mod=readonly`,
   so a module that `go.sum` does not vouch for stops the build; and `CGO_ENABLED=0`, a static
   binary;
3. runs `go vet .` and then `go build -o out/natsgo-consumer .`;
4. checks, with `go version -m`, that the binary was built by go1.26.0 on nats.go v1.54.0, keeps
   that record in `out/BUILD_INFO.txt`, and writes the binary's SHA-256 to `out/SHA256SUM`.

**The toolchain is not harness/go's.** nats.go v1.54.0's `go.mod` says `go 1.26.0`, and so do
those of golang.org/x/crypto v0.57.0 and golang.org/x/sys v0.48.0, which it requires. go1.23.11,
which builds harness/go, refuses them, and go1.26.0 is the least they accept. natscli, at the
commit `cloud/azure/tools.sh` pins for nats-latency and nats-bench (cc0a8e32), says `go 1.26.0`
too, and requires nats.go v1.53.1: with no newer Go installed, `go install` switches to go1.26.0
for it. The newest nats.go that go1.23.11 could build is v1.48.0, whose `go.mod` says `go 1.23.0`.

| Pinned | Version | Where the version comes from |
|---|---|---|
| github.com/nats-io/nats.go | v1.54.0 | the latest release: the module proxy's `@latest` and GitHub's latest release (18 Sep 2026, not a prerelease), read 23 Oct 2026; its tag is commit 7a8404ab |
| github.com/klauspost/compress | v1.20.0 | nats.go v1.54.0's `go.mod` |
| github.com/nats-io/nkeys | v0.4.16 | nats.go v1.54.0's `go.mod` |
| github.com/nats-io/nuid | v1.0.1 | nats.go v1.54.0's `go.mod` |
| golang.org/x/crypto | v0.57.0 | nats.go v1.54.0's `go.mod` |
| golang.org/x/sys | v0.48.0 | nats.go v1.54.0's `go.mod` |
| toolchain | go1.26.0 | the least the modules above accept (`go 1.26.0`) |

The checksums in `go.sum` are the Go checksum database's (sum.golang.org), and nats.go's own
`go.sum` at v1.54.0 holds the same lines for its five requirements. The module's `go` line, 1.26.0,
is the least its requirements accept. `go.mod` has no `toolchain` line: one naming go1.26.0 beside
`go 1.26.0` would say nothing more, and the go command drops such a line whenever it rewrites the
file, which `-mod=readonly` turns into a stopped build (`UpdateGoModFromReqs` and
`modFileIsDirty`, `cmd/go/internal/modload`, read in go1.26.0). `build.sh` names the toolchain
instead. `out/` is not committed.

The kit runs it as:

    harness/go-nats/out/natsgo-consumer --run-id <id> --out runs/<id>/consumer.csv \
        --host <host> --port 4222 --stream <stream> --subject <subject> --durable <durable> \
        --storage memory --idle-seconds <n> [--threads-out runs/<id>/consumer_tids.csv]

## What only the driver can confirm

*Words in this part.* **Toolchain**: the compiler, at one version. **Pull request**: the request
for the next messages, which waits at the server.

Nothing here has been compiled or run: no Go toolchain is on the machine it was written on.

- That it compiles, and that `go vet` passes, with go1.26.0: `build.sh` does both.
- The thread names: the list from `--threads-out`, read against `/proc` while it runs.
- That `Consume` keeps a request waiting at 2,000 messages a second: the count above, read from the
  captures of a pilot run.

## Checked without a Go toolchain

*Words in this part.* **CI**: the tests run on every push, on machines with no Go installed.

`tests/unit/test_go_nats_consumer.py` reads `main.go`, `go.mod`, `go.sum` and `build.sh` and holds
them to the interface: the flags and their defaults against `nats_consumer.py`'s, the columns, the
stamps, the stream sequence from the metadata, `Consume` with nats.go's pull options, the stream
and the durable consumer against `nats_wire.py`'s, the pins, every import used, a `go.sum` line
for every module `go.mod` names, and `build.sh` against `harness/go/build.sh`. They are source
checks, because CI has no Go toolchain and no test in the suite may skip. The compiler's own check
is `build.sh`'s `go vet` and `go build`, on the driver.

## Probes of the connection

`--probe-ms` (default 100; 0 keeps nats.go's own interval, two minutes) sets nats.go's own ping,
`PingInterval`, so that the connection carries a PING every 100 ms, as `nats_consumer.py`'s
`--probe-ms` does. The reader times each PING and its PONG on the client host's capture: the
least round trip is the connection's floor, and the largest a check that every one-way delay
stayed under the bound the check of a request waiting rests on. `MaxPingsOut` is set out of a
stall's reach, so that a slow PONG is measured and not taken for a lost connection. The value used
is in the `CONFIG effective` line, as `probe_ms`.
