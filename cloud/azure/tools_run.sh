#!/usr/bin/env bash
# Run one tool once, against the broker its own documentation says it runs on.
#
# One place decides how each tool is invoked, so T1, T3 and T4 differ in the conditions they set
# and in nothing else. SBL_TOOL_WRAP prefixes the tool's own process, which is how T3 gives it
# go-first priority without touching anything else.
#
# Like every campaign here, it carries on past a failing command so that a failure is reported
# rather than swallowed.
. "$(dirname "${BASH_SOURCE[0]}")/../campaigns/common.sh"
set +e
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)" || exit 1

TOOL="${1:?which tool}"
OUT="${2:?where to write}"
WRAP="${SBL_TOOL_WRAP:-}"
SECONDS_TO_RUN="${SBL_TOOL_SECONDS:-60}"
RATE="${SBL_TOOL_RATE:-50}"
#: Across the pair, not around the loopback. Every default here used to be 127.0.0.1, which
#: meant the tool and the server it talked to were the same machine -- and T1 adds its delay on
#: the broker's card, to traffic bound for the driver, so the delay landed on a path the tool
#: never used and T1 could not work at all. Running the tool on the driver against the broker
#: puts it on the path the delay is added to, which is the path our own program is measured on,
#: and that is the comparison this block exists to make.
TARGET_HTTP="${SBL_TOOL_HTTP:-http://$BROKER_PRIV:8080/}"
VALKEY_HOST="${SBL_VALKEY_HOST:-$BROKER_PRIV}"
KAFKA="${SBL_KAFKA:-$BROKER_PRIV:19092}"
RABBIT="${SBL_RABBIT:-amqp://guest:guest@$BROKER_PRIV:5672}"
NATS="${SBL_NATS:-nats://$BROKER_PRIV:4222}"
PERFTEST_JAR="${SBL_PERFTEST_JAR:-$HOME/tools/perf-test.jar}"
#: Freeze 30's five (D33-1): where `tools.sh install` puts them, and the servers they speak to.
PULSAR="${SBL_PULSAR:-pulsar://$BROKER_PRIV:6650}"
MQTT_HOST="${SBL_MQTT_HOST:-$BROKER_PRIV}"
OMB_HOME="${SBL_OMB_HOME:-$HOME/tools/omb}"
PULSAR_HOME="${SBL_PULSAR_HOME:-$HOME/tools/pulsar}"
YCSB_HOME="${SBL_YCSB_HOME:-$HOME/tools/ycsb}"
EMQTT_BENCH="${SBL_EMQTT_BENCH:-$HOME/tools/emqtt-bench/emqtt_bench}"
OTP_BIN="${SBL_OTP_BIN:-$HOME/tools/otp/bin}"
JAVA17="${SBL_JAVA17:-/usr/lib/jvm/java-17-openjdk-amd64}"
JAVA11="${SBL_JAVA11:-/usr/lib/jvm/java-11-openjdk-amd64}"
#: The one address here that is not across the pair. Two of these tools are made of processes
#: that talk to one another -- OMB's coordinator to its two workers, emqtt-bench's subscriber
#: serving its own metrics -- and they do it on the machine's loopback. It names the tool's own
#: processes, never a server any tool is timed against.
OWN="${SBL_TOOL_OWN:-127.0.0.1}"
#: Where the wrap puts the tool, and what else it does. T1, T3 and T4 run a tool inside the
#: receiver's namespace and T2 on the machine itself. For a tool made of several processes the
#: network is all of theirs -- a process in the namespace cannot reach one outside it on this
#: machine -- while the rest of the wrap, go-first or a moved clock, belongs to the process that
#: subtracts and to it alone.
case "$WRAP" in
  *"ip netns exec sblrecv"*) NS="sudo ip netns exec sblrecv"; REST="${WRAP#*sblrecv}" ;;
  *) NS=""; REST="$WRAP" ;;
esac
#: The processes a tool leaves running in the background, stopped however the run ends: a worker
#: left holding its port would refuse the next run. By process and by a pattern only that run's
#: processes carry, because a process started under faketime is faketime's child, and faketime
#: does not pass a signal on to it.
OWN_PIDS=""
OWN_PATTERN=""
stop_own () {
  local pid
  for pid in $OWN_PIDS; do
    sudo kill "$pid" 2>/dev/null || kill "$pid" 2>/dev/null
  done
  [ -n "$OWN_PATTERN" ] && sudo pkill -f -- "$OWN_PATTERN" 2>/dev/null
  OWN_PIDS=""
  OWN_PATTERN=""
  return 0
}
trap stop_own EXIT

#: A tool that never finishes must not take the pair with it.
#:
#: rdkafka_performance's consumer waits for messages that are not coming and says so once a
#: second for ever; the only limit above it was the queue's own twelve hours, and it had a
#: whole pair to itself for twenty-eight minutes before anyone looked. Six times the run's own
#: length is far longer than any of these tools takes and far shorter than a night.
LIMIT="${SBL_TOOL_LIMIT:-$(( SECONDS_TO_RUN * 6 + 120 ))}"
if [ -z "${SBL_TOOL_GUARDED:-}" ]; then
  export SBL_TOOL_GUARDED=1
  exec timeout -k 30 "$LIMIT" bash "${BASH_SOURCE[0]}" "$TOOL" "$OUT"
fi

mkdir -p "$OUT"
#: How many this run asks the tool to send, written beside it: T2 holds the tool's own count
#: against this. It held it against the number of trips in our reference -- another run, of
#: another client -- and on 25 September wrk2, which counted all 3,001 it sent, read as short.
echo $(( RATE * SECONDS_TO_RUN )) > "$OUT/asked_to_send.txt"
# shellcheck disable=SC2086
case "$TOOL" in
  vegeta)
    echo "GET $TARGET_HTTP" | $WRAP vegeta attack -rate="$RATE" -duration="${SECONDS_TO_RUN}s" \
      | $WRAP vegeta report ;;
  hey)
    $WRAP hey -z "${SECONDS_TO_RUN}s" -q "$RATE" -c 1 "$TARGET_HTTP" ;;
  k6)
    cat > "$OUT/script.js" <<'JS'
import http from 'k6/http';
import { sleep } from 'k6';
export const options = { vus: 1, duration: __ENV.SBL_DURATION || '60s' };
export default function () { http.get(__ENV.SBL_TARGET); sleep(1.0 / Number(__ENV.SBL_RATE)); }
JS
    # k6's own defaults stop at p(95), so a run left alone reports no 99th percentile at all.
    #
    # Its settings go in as flags (D25-3). They went in through the environment, and every stage
    # runs the tool through `sudo ip netns exec`, which clears it: k6 got no URL and no rate,
    # looped 4,895,826 times in 60 s on "invalid URL" without sending a byte, and all fifteen of
    # its runs of 24 September measured nothing. `sudo` keeps a command's arguments.
    $WRAP k6 run --env SBL_DURATION="${SECONDS_TO_RUN}s" --env SBL_TARGET="$TARGET_HTTP" \
      --env SBL_RATE="$RATE" --summary-trend-stats="avg,min,med,p(99),max" "$OUT/script.js" ;;
  valkey-benchmark)
    # --latency-history belongs to valkey-cli, not to this tool; its own summary table is what
    # is read here, and -q or --csv would suppress it.
    $WRAP valkey-benchmark -h "$VALKEY_HOST" -t get -n $((RATE * SECONDS_TO_RUN)) -c 1 ;;
  memtier_benchmark)
    $WRAP memtier_benchmark -s "$VALKEY_HOST" -p 6379 --protocol=redis --clients=1 \
      --threads=1 --test-time="$SECONDS_TO_RUN" --rate-limiting="$RATE" ;;
  rdkafka_performance)
    # Its -l latency mode "needs two matching instances, one consumer and one producer, both
    # running with the -l switch" (its own usage text): the producer stamps the payload and the
    # consumer subtracts, so the consumer is the one that prints a latency and the producer alone
    # would print none. -A also writes every message's latency, which T1 reads beside the summary.
    # This is the only tool of the eleven whose subtraction spans two clocks, so it is the only
    # one T2 can ask its question of, and $WRAP is on the consumer alone.
    #
    # -p 0 is what makes it read anything. Its usage says the partition "defaults to random", and
    # without one the consumer never attaches to a partition: it printed nothing at all and
    # consumed nothing, over a whole staircase and again with the producer first. The shakedown
    # of 23 September (docs/results/tools/rdkafka-shakedown.md) has the trials -- the same
    # invocation with -p 0 read every message the producer sent, on a one-partition topic.
    #
    # -o end so a run measures its own messages. The default is the beginning of the topic, not
    # the end as the note here used to say: without it the consumer read the previous run's
    # messages too and reported their age as latency.
    #
    # -r is the pacing every other tool in this block gets. Without it the producer enqueues the
    # whole count at once, and what comes out is its own batching rather than a trip.
    $WRAP rdkafka_performance -C -l -t sbl-tools -p 0 -o end -b "$KAFKA" \
      -c $((RATE * SECONDS_TO_RUN)) -A "$OUT/per_message_us.txt" &
    consumer=$!
    sleep 5
    rdkafka_performance -P -l -t sbl-tools -b "$KAFKA" -c $((RATE * SECONDS_TO_RUN)) \
      -s 512 -a 1 -r "$RATE" > "$OUT/producer.txt" 2>&1
    wait "$consumer" 2>/dev/null ;;
  kafka-end-to-end)
    # Kafka moved this tool out of the kafka.tools package; the old name is kept for the pinned
    # build that still has it, and whichever answers is the one whose output is read.
    $WRAP kafka-run-class.sh org.apache.kafka.tools.EndToEndLatency "$KAFKA" sbl-tools \
      $((RATE * SECONDS_TO_RUN)) 1 512 2>/dev/null \
      || $WRAP kafka-run-class.sh kafka.tools.EndToEndLatency "$KAFKA" sbl-tools \
        $((RATE * SECONDS_TO_RUN)) 1 512 ;;
  kafka-producer-perf)
    $WRAP kafka-producer-perf-test.sh --topic sbl-tools \
      --num-records $((RATE * SECONDS_TO_RUN)) --record-size 512 --throughput "$RATE" \
      --producer-props bootstrap.servers="$KAFKA" acks=1 ;;
  wrk2)
    # --latency is what prints the HdrHistogram distribution; without it there are no
    # percentiles to read, only the thread average.
    $WRAP wrk -t1 -c1 -d"${SECONDS_TO_RUN}s" -R"$RATE" --latency "$TARGET_HTTP" ;;
  rabbitmq-perftest)
    $WRAP java -jar "$PERFTEST_JAR" --uri "$RABBIT" --producers 1 --consumers 1 \
      --rate "$RATE" --time "$SECONDS_TO_RUN" --size 512 --queue sbl-tools ;;
  nats-latency)
    # Its --server-b is required: it publishes on one connection and subscribes on another, and
    # the one server here answers both, which is the round trip we want timed.
    $WRAP nats latency --server "$NATS" --server-b "$NATS" --size 512 --rate "$RATE" \
      --duration "${SECONDS_TO_RUN}s" ;;
  omb)
    # The OpenMessaging Benchmark in its distributed mode, as it is designed to be run: a worker
    # that produces, a worker that consumes, and the coordinator that drives them -- so the two
    # timestamps of its end-to-end latency are taken in two processes. That mode never completed
    # a run on the July testbed; here it did, in the pilot of 9 October. Its Kafka driver is its
    # own kafka-latency.yaml with only what one broker needs changed, a replication factor and a
    # minimum in-sync count of one. The workload is the block's: one topic of one partition,
    # 512-byte messages at RATE for the run's length, after the benchmark's own default warm-up
    # of a minute. The coordinator gives the first worker the producers and the second the
    # consumers, and the second is the one that subtracts, so the rest of the wrap is on it.
    here="$(cd "$OUT" && pwd)"
    head -c 512 /dev/zero | tr '\0' 'x' > "$here/payload.data"
    sed -e 's/^replicationFactor: 3$/replicationFactor: 1/' \
        -e 's/min.insync.replicas=2/min.insync.replicas=1/' \
        -e "s/bootstrap.servers=.*/bootstrap.servers=$KAFKA/" \
        "$OMB_HOME/driver-kafka/kafka-latency.yaml" > "$here/driver.yaml"
    printf 'name: sbl-tools\ntopics: 1\npartitionsPerTopic: 1\nmessageSize: 512\npayloadFile: "%s"\nsubscriptionsPerTopic: 1\nconsumerPerSubscription: 1\nproducersPerTopic: 1\nproducerRate: %s\nconsumerBacklogSizeGB: 0\ntestDurationMinutes: %s\n' \
      "$here/payload.data" "$RATE" "$(( (SECONDS_TO_RUN + 59) / 60 ))" > "$here/workload.yaml"
    #: Each of the three in the benchmark's own folder, whose lib/ its launchers put on the class
    #: path, and on Java 17, with the launchers' own default heap.
    in_omb="cd '$OMB_HOME' && export PATH='$JAVA17/bin':/usr/bin:/bin && exec"
    OWN_PATTERN="--stats-port 818[13]"
    $NS sh -c "$in_omb bin/benchmark-worker --port 8180 --stats-port 8181" \
      > "$here/producer_worker.txt" 2>&1 &
    OWN_PIDS="$OWN_PIDS $!"
    $NS $REST sh -c "$in_omb bin/benchmark-worker --port 8182 --stats-port 8183" \
      > "$here/consumer_worker.txt" 2>&1 &
    OWN_PIDS="$OWN_PIDS $!"
    sleep 15
    $NS sh -c "$in_omb bin/benchmark --workers http://$OWN:8180,http://$OWN:8182 \
      --drivers '$here/driver.yaml' --output '$here/omb_result.json' '$here/workload.yaml'"
    stop_own
    echo "# the benchmark's result file"
    cat "$here/omb_result.json" 2>/dev/null ;;
  pulsar-perf)
    # Apache Pulsar's performance client at release 4.2.4: a consumer and a producer, two
    # processes, the consumer subtracting the producer's publish stamp from its own clock and
    # keeping the difference only when it is at or above zero. Like rdkafka_performance's, the
    # consumer is the one that subtracts and prints, so the wrap is on it alone, and it listens
    # before anything is sent. Each run has a topic of its own and starts at its latest message:
    # a consumer that drained an earlier run's messages would report their age as their latency,
    # which is what a user of the tool reported in its tracker (apache/pulsar#23879).
    #
    # It runs for a time rather than to a count, and writes its histogram file. Stopped by a
    # count, it exits on the last message before recording that message's latency and before
    # writing the last ten seconds to the file; stopped by its own clock after the producer has
    # finished, it writes every interval first. The file is the only place it says how many
    # latencies it kept, and the only way to tell its empty histogram's zeros from real ones.
    topic="persistent://public/default/sbl-tools-$(date -u +%s%N)"
    histogram="$(cd "$OUT" && pwd)/histogram.hlog"
    $WRAP env JAVA_HOME="$JAVA17" "$PULSAR_HOME/bin/pulsar-perf" consume -u "$PULSAR" -ss sbl \
      -sp Latest -time $((SECONDS_TO_RUN + 30)) --histogram-file "$histogram" "$topic" &
    consumer=$!
    sleep 10
    env JAVA_HOME="$JAVA17" "$PULSAR_HOME/bin/pulsar-perf" produce -u "$PULSAR" -r "$RATE" -s 512 \
      -m $((RATE * SECONDS_TO_RUN)) "$topic" > "$OUT/producer.txt" 2>&1
    wait "$consumer" 2>/dev/null
    echo "# pulsar-perf's histogram file"
    cat "$histogram" 2>/dev/null ;;
  emqtt-bench)
    # emqtt-bench at tag 0.6.3: a subscriber and a publisher, two processes, the publisher
    # stamping each payload with its own millisecond clock (--payload-hdrs ts) and the subscriber
    # subtracting it from its own. The subscriber subtracts and prints, so the rest of the wrap is
    # on it. Its console prints an average once a second; its histogram of every latency is on its
    # Prometheus page, which is read once the publisher has finished and written after the
    # console's lines, under a line of its own. The publisher's interval is RATE's, in whole
    # milliseconds, which is the tool's own unit for it.
    topic="sbl/tools/$(date -u +%s%N)"
    OWN_PATTERN="sub -h $MQTT_HOST -p 1883 -t $topic"
    $NS env PATH="$OTP_BIN:/usr/bin:/bin" $REST "$EMQTT_BENCH" sub -h "$MQTT_HOST" -p 1883 \
      -t "$topic" -c 1 -q 0 --payload-hdrs ts --prometheus --restapi "$OWN:9091" &
    OWN_PIDS="$OWN_PIDS $!"
    sleep 5
    env PATH="$OTP_BIN:$PATH" "$EMQTT_BENCH" pub -h "$MQTT_HOST" -p 1883 -t "$topic" -c 1 \
      -I $((1000 / RATE)) -s 512 --payload-hdrs ts -L $((RATE * SECONDS_TO_RUN)) \
      > "$OUT/publisher.txt" 2>&1
    sleep 3
    echo "# emqtt-bench's /metrics, read at the end of the run"
    $NS curl -s -m 10 "http://$OWN:9091/metrics"
    stop_own ;;
  ycsb)
    # YCSB's Redis binding: one client thread reading 512-byte records at RATE, each read timed on
    # System.nanoTime() inside the client, against the broker's Redis. It reads only what it has
    # loaded, so the records are loaded first, outside the wrap and outside the run's timing, the
    # same thousand every time. It is asked for its 50th percentile beside its 99th, as k6 is.
    ycsb_props="-P $YCSB_HOME/workloads/workloadc -p redis.host=$VALKEY_HOST -p redis.port=6379 \
      -p recordcount=1000 -p fieldcount=1 -p fieldlength=512"
    env JAVA_HOME="$JAVA11" "$YCSB_HOME/bin/ycsb.sh" load redis $ycsb_props -threads 1 \
      > "$OUT/load.txt" 2>&1
    $WRAP env JAVA_HOME="$JAVA11" "$YCSB_HOME/bin/ycsb.sh" run redis $ycsb_props -threads 1 \
      -p operationcount=$((RATE * SECONDS_TO_RUN)) -p target="$RATE" \
      -p hdrhistogram.percentiles=50,99 ;;
  nats-bench)
    # The NATS CLI's benchmark, the build nats-latency is, in its request mode: each request timed
    # to its reply on Go's monotonic clock inside one process. The replies come from the same
    # CLI's service mode, started first, on the machine itself; only the requester is wrapped.
    nats bench service serve sbl.bench --server "$NATS" --size 512 --no-progress \
      > "$OUT/server.txt" 2>&1 &
    OWN_PIDS="$OWN_PIDS $!"
    sleep 3
    $WRAP nats bench service request sbl.bench --server "$NATS" --clients 1 --size 512 \
      --throughput "$RATE" --duration "${SECONDS_TO_RUN}s" --no-progress
    stop_own ;;
  *)
    echo "no such tool here: $TOOL" >&2; exit 2 ;;
esac
