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
#: Freeze 32's four (D35-1): where `tools.sh install` puts them. Trogdor is the Kafka release's.
XINFRA_HOME="${SBL_XINFRA_HOME:-$HOME/tools/src/kafka-monitor}"
KAFKA_HOME="${SBL_KAFKA_HOME:-$HOME/tools/kafka_2.13-3.7.1}"
STREAM_PERF_JAR="${SBL_STREAM_PERF_JAR:-$HOME/tools/stream-perf-test.jar}"
#: The Kafka 3.9.1 broker the canary runs against, since its client cannot commit to 4.x (D35-5).
KAFKA39="${SBL_KAFKA39:-$BROKER_PRIV:19094}"
#: Freeze 33's YSB (D36-1): where `tools.sh install` puts it and the Flink it runs on, and its own
#: defaults for the load, 1,000 events a second (stream-bench.sh's LOAD); the test is two minutes
#: of its windows of ten seconds where its script's default is four (its TEST_TIME).
YSB_HOME="${SBL_YSB_HOME:-$HOME/tools/src/streaming-benchmarks}"
FLINK_HOME="${SBL_FLINK_HOME:-$HOME/tools/flink-1.11.0}"
YSB_LOAD="${SBL_YSB_LOAD:-1000}"
YSB_TEST_TIME="${SBL_YSB_TEST_TIME:-120}"
#: Freeze 34's PerfKit messaging client, laid out as on PerfKit's client VM, and its own defaults:
#: 100 messages of 10 characters, no warm-up (messaging_service_benchmark.py:72-100).
PKB_VM="${SBL_PKB_VM:-$HOME/tools/pkb-vm}"
PKB_MESSAGES="${SBL_PKB_MESSAGES:-100}"
PKB_SIZE="${SBL_PKB_SIZE:-10}"
#: Freeze 35's four (D38-2): SBK where `tools.sh install-for sbk` builds it, on the Java 25 its
#: build requires; the three Go tools are on the path, kgo-repeater on the broker too.
SBK_HOME="${SBL_SBK_HOME:-$HOME/tools/src/SBK}"
JAVA25="${SBL_JAVA25:-$HOME/tools/jdk-25}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/azure_sbl}"
#: Freeze 36's three (D39-2): the clients, where `tools.sh install-for` unpacks their releases.
ARTEMIS_CLIENT="${SBL_ARTEMIS_CLIENT:-$HOME/tools/artemis-client}"
ROCKETMQ_HOME="${SBL_ROCKETMQ_HOME:-$(ls -d "$HOME"/tools/rocketmq-all-5.5.1* 2>/dev/null | head -1)}"
BOOKKEEPER_HOME="${SBL_BOOKKEEPER_HOME:-$(ls -d "$HOME"/tools/bookkeeper-all-4.18.1* 2>/dev/null | head -1)}"
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
#: Nothing an earlier run left behind runs beside this one. In the pilot of 11 October Xinfra
#: Monitor outlived its run by twenty minutes, sending and timing fifty messages a second through
#: every run after it, and nothing noticed. On the driver every process of these names is one of
#: the tools -- the broker is the other machine -- so any found is stopped first and written down
#: beside the run, with its command line.
leftover=$(pgrep -a -f '^([^ ]*/)?(java|beam\.smp|strimzi-canary|vegeta|hey|k6|nats|wrk|memtier_benchmark|valkey-benchmark|rdkafka_performance|mqtt-benchmark|kafka-producer-performance|kgo-repeater)( |$)' 2>/dev/null)
if [ -n "$leftover" ]; then
  echo "$leftover" > "$OUT/leftovers.txt"
  echo "$leftover" | awk '{print $1}' | xargs -r sudo kill -9 2>/dev/null
  echo "stopped $(echo "$leftover" | wc -l) process(es) an earlier run left; see $OUT/leftovers.txt" >&2
  sleep 1
fi
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
  xinfra-monitor)
    # Xinfra Monitor as its README runs it: one JVM holding a single-cluster monitor, which
    # produces to and consumes from a topic of its own, and the reporter that logs the consume
    # service's metrics once a second. Its configuration requires a ZooKeeper address that no code
    # at this commit contacts (D35-3), and a single broker gives its topic one partition. A 20 ms
    # pause between sends, each waiting for its acknowledgment as the monitor does by default,
    # puts it near the block's rate; its latency metrics are a rolling minute, so it runs for the
    # block's length and long enough before it for that minute to be all steady state.
    xm_topic="sbl-xinfra-$(date +%s)"
    cat > "$OUT/xm.properties" <<XM
{
  "single-cluster-monitor": {
    "class.name": "com.linkedin.xinfra.monitor.apps.SingleClusterMonitor",
    "topic": "$xm_topic",
    "zookeeper.connect": "unused:2181",
    "bootstrap.servers": "$KAFKA",
    "produce.record.delay.ms": 20,
    "produce.record.size.byte": 512,
    "topic-management.topicManagementEnabled": true,
    "topic-management.topicCreationEnabled": true,
    "topic-management.replicationFactor": 1,
    "topic-management.partitionsToBrokersRatio": 1.0,
    "topic-management.topicReassignPartitionAndElectLeaderEnabled": false
  },
  "reporter-service": {
    "class.name": "com.linkedin.xinfra.monitor.services.DefaultMetricsReporterService",
    "report.interval.sec": 1,
    "report.metrics.list": [
      "kmf.services:type=consume-service,name=*:records-delay-ms-avg",
      "kmf.services:type=consume-service,name=*:records-delay-ms-max",
      "kmf.services:type=consume-service,name=*:records-delay-ms-99th",
      "kmf.services:type=consume-service,name=*:records-delay-ms-999th",
      "kmf.services:type=consume-service,name=*:records-consumed-total"
    ]
  }
}
XM
    here="$(cd "$OUT" && pwd)"
    #: Stopped by a pattern only this run's JVM carries, as the tools made of several processes
    #: are. In the pilot of 11 October it ran under `timeout`, which stopped sudo and not the JVM
    #: inside the namespace: the monitor ran on for twenty minutes, through every later run, into
    #: this run's file. Its console is what is read; the log directory it also writes is shared
    #: by every run and would carry the others' lines.
    #: Anchored at the JVM's own path, which no sudo or pkill command line begins with: an
    #: unanchored pattern can match the command that sends it.
    OWN_PATTERN="^[^ ]*/java .*xinfra.*$here/xm.properties"
    #: S1 (freeze 34, D37-4): a value below its percentiles' floor is pinned to the floor, and
    #: kafka-clients says so only at debug level (Percentiles.java:119-122 at 2.8.2). Its own
    #: logging configuration, with that one logger at debug, writing to the console and nowhere
    #: else, makes the line part of what is read. Its parent, org.apache.kafka, writes to a file
    #: every run shares and passes nothing up, so a logger that inherited it put the pilot's 67
    #: lines in that file and none on the console.
    xm_log4j=""
    if [ -n "${SBL_S1:-}" ]; then
      cp "$XINFRA_HOME/config/log4j2.properties" "$here/log4j2.properties"
      printf '%s\n' "" "logger.pinned.name = org.apache.kafka.common.metrics.stats.Percentiles" \
        "logger.pinned.level = debug" "logger.pinned.additivity = false" \
        "logger.pinned.appenderRef.console.ref = STDOUT" >> "$here/log4j2.properties"
      xm_log4j="-Dlog4j.configurationFile=$here/log4j2.properties"
    fi
    ( cd "$XINFRA_HOME" && $WRAP env JAVA_HOME="$JAVA11" KAFKA_LOG4J_OPTS="$xm_log4j" \
        bin/xinfra-monitor-start.sh "$here/xm.properties" ) &
    OWN_PIDS="$OWN_PIDS $!"
    sleep $((SECONDS_TO_RUN + 40))
    stop_own
    sleep 2
    sudo pkill -9 -f -- "^[^ ]*/java .*xinfra.*$here/xm.properties" 2>/dev/null
    true ;;
  strimzi-canary)
    # Strimzi Canary standalone, configured as its README configures it, against the Kafka 3.9.1
    # broker its client can still commit offsets to (D35-5): one process, a producer
    # and a consumer on a topic of its own, which a single broker gives one partition. It sends one
    # message per partition per reconcile tick, so a 20 ms tick is the block's rate; it is told the
    # cluster has one broker, so it does not ask for a reassignment every tick, and to log each
    # message's duration. Its histogram lives in the process, so /metrics is read before it stops.
    c_id="sbl-canary-$(date +%s)"
    $NS env KAFKA_BOOTSTRAP_SERVERS="$KAFKA39" TOPIC="$c_id" CONSUMER_GROUP_ID="$c_id" \
      CLIENT_ID="$c_id" RECONCILE_INTERVAL_MS=20 EXPECTED_CLUSTER_SIZE=1 \
      CONNECTION_CHECK_INTERVAL_MS=600000 VERBOSITY_LOG_LEVEL=1 \
      $REST strimzi-canary > "$OUT/canary.log" 2>&1 &
    OWN_PIDS="$OWN_PIDS $!"
    sleep $((SECONDS_TO_RUN + 10))
    echo "# the canary's /metrics, read at the end of the run"
    $NS curl -s -m 5 "http://$OWN:8080/metrics"
    c_pids=$(pgrep -x strimzi-canary)
    [ -n "$c_pids" ] && sudo kill $c_pids 2>/dev/null
    stop_own
    echo "# the canary's log"
    cat "$OUT/canary.log"
    #: Freeze 34: the reader the canary's repository ships for that log, run on it, whose pattern
    #: cannot match a minus sign (tools/canary_latencies.py:19).
    echo "# the canary's own log reader on that log"
    python3 "$HOME/tools/src/strimzi-canary/tools/canary_latencies.py" -f "$OUT/canary.log" 2>&1 \
      | head -n 40 ;;
  trogdor)
    # Kafka's Trogdor from the 3.7.1 release, as its README runs it: a coordinator and agents,
    # given workloads as JSON specs. ProduceBench on one agent writes its wall clock into each
    # record (the timestampConstant payload), and ConsumeBench on another, with its timestamp
    # record processor, subtracts its own: two processes, as Trogdor's agents are meant to be, so
    # the rest of the wrap -- go-first or a moved clock -- reaches the agent that subtracts alone.
    here="$(cd "$OUT" && pwd)"
    t_topic="sbl-trogdor-$(date +%s)"
    #: ConsumeBench reports its status only once its task has ended, not while it runs: in the
    #: pilot of 11 October it was asked at ninety seconds of a two-minute task and said "null".
    #: So its task ends at a fixed time, thirty seconds after the producer's minute would, and is
    #: asked only after that; the producer stops at its count, the block's minute of messages.
    t_consume_ms=$(( (SECONDS_TO_RUN + 30) * 1000 ))
    t_produce_ms=$(( (SECONDS_TO_RUN + 20) * 1000 ))
    printf '{"_comment":"sbl","platform":"org.apache.kafka.trogdor.basic.BasicPlatform","nodes":{"node0":{"hostname":"%s","trogdor.agent.port":8888,"trogdor.coordinator.port":8889},"node1":{"hostname":"%s","trogdor.agent.port":8890}}}\n' \
      "$OWN" "$OWN" > "$here/trogdor.conf"
    printf '{"class":"org.apache.kafka.trogdor.workload.ProduceBenchSpec","startMs":0,"durationMs":%s,"producerNode":"node0","bootstrapServers":"%s","targetMessagesPerSec":%s,"maxMessages":%s,"valueGenerator":{"type":"timestampConstant","size":512},"activeTopics":{"%s":{"numPartitions":1,"replicationFactor":1}},"inactiveTopics":{}}\n' \
      "$t_produce_ms" "$KAFKA" "$RATE" $((RATE * SECONDS_TO_RUN)) "$t_topic" > "$here/produce.json"
    printf '{"class":"org.apache.kafka.trogdor.workload.ConsumeBenchSpec","startMs":0,"durationMs":%s,"consumerNode":"node1","bootstrapServers":"%s","maxMessages":%s,"activeTopics":["%s"],"recordProcessor":{"type":"timestamp","histogramMaxMs":10000,"histogramMinMs":0,"histogramStepMs":1}}\n' \
      "$t_consume_ms" "$KAFKA" $((RATE * SECONDS_TO_RUN)) "$t_topic" > "$here/consume.json"
    "$KAFKA_HOME/bin/kafka-topics.sh" --bootstrap-server "$KAFKA" --create --topic "$t_topic" \
      --partitions 1 --replication-factor 1 > "$here/topic.txt" 2>&1
    OWN_PATTERN="trogdor\\.(coordinator|agent)\\..* -c $here/trogdor.conf"
    $NS "$KAFKA_HOME/bin/trogdor.sh" coordinator -n node0 -c "$here/trogdor.conf" \
      > "$here/coordinator.txt" 2>&1 &
    OWN_PIDS="$OWN_PIDS $!"
    $NS "$KAFKA_HOME/bin/trogdor.sh" agent -n node0 -c "$here/trogdor.conf" \
      > "$here/agent_producer.txt" 2>&1 &
    OWN_PIDS="$OWN_PIDS $!"
    $NS $REST "$KAFKA_HOME/bin/trogdor.sh" agent -n node1 -c "$here/trogdor.conf" \
      > "$here/agent_consumer.txt" 2>&1 &
    OWN_PIDS="$OWN_PIDS $!"
    sleep 15
    $NS "$KAFKA_HOME/bin/trogdor.sh" client createTask -t "$OWN:8889" -i consume \
      --spec "$here/consume.json" > "$here/create_consume.txt" 2>&1
    sleep 5
    $NS "$KAFKA_HOME/bin/trogdor.sh" client createTask -t "$OWN:8889" -i produce \
      --spec "$here/produce.json" > "$here/create_produce.txt" 2>&1
    # The consume task was made five seconds before the produce task, so it has ended by now.
    sleep $((SECONDS_TO_RUN + 26))
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      $NS "$KAFKA_HOME/bin/trogdor.sh" client showTask -t "$OWN:8889" -i consume \
        | grep -q " is DONE" && break
      sleep 3
    done
    echo "# trogdor's consume task"
    $NS "$KAFKA_HOME/bin/trogdor.sh" client showTask -t "$OWN:8889" -i consume --show-status
    echo "# trogdor's produce task"
    $NS "$KAFKA_HOME/bin/trogdor.sh" client showTask -t "$OWN:8889" -i produce --show-status
    stop_own ;;
  stream-perftest)
    # RabbitMQ Stream PerfTest in the arrangement its source stamps each message for, the wall
    # clock "for interoperability with other tools and also across different processes"
    # (StreamPerfTest.java:1315-1316 at 1.8.0): a consumer-only instance and a producer-only one,
    # which its options allow (--producers 0, --consumers 0). The consumer subtracts, so it is the
    # instance wrapped, and it is started first on a stream of its own; the producer sends at the
    # block's rate and size for the block's minute, and the consumer stops fifteen seconds after
    # it, deleting the stream. Each prints the last second's figures once a second; only the
    # consumer's lines hold a latency, and only they are written where the reader reads (D35-4).
    # The broker's RabbitMQ is 3.9, older than the leader locator the tool asks for by default --
    # "balanced (RabbitMQ 3.10)", its own help says -- so both instances ask for client-local, the
    # only other value its option accepts at 1.8.0 (its help lists four), which on a single node
    # places the stream where balanced would.
    here="$(cd "$OUT" && pwd)"
    s_name="sbl-stream-$(date +%s)"
    s_args=(--uris "rabbitmq-stream://guest:guest@$BROKER_PRIV:5552" --streams "$s_name"
            --leader-locator client-local)
    #: The consumer also serves its metrics (--prometheus, a documented option), read once the
    #: producer has finished: its latency timer's count is the one record of how many latencies it
    #: kept. Its line a second prints 0/0/0/0 for a second in which it kept none, and in the pilot
    #: of 11 October, with its clock 5 ms behind, it printed that for every second while it
    #: consumed fifty messages a second and dropped every one.
    $NS $REST env JAVA_HOME="$JAVA11" "$JAVA11/bin/java" -jar "$STREAM_PERF_JAR" "${s_args[@]}" \
      --producers 0 --consumers 1 --time $((SECONDS_TO_RUN + 25)) --delete-streams --prometheus \
      > "$here/consumer.txt" 2>&1 &
    s_consumer=$!
    OWN_PIDS="$OWN_PIDS $s_consumer"
    OWN_PATTERN="stream-perf-test\\.jar .*$s_name"
    sleep 10
    $NS env JAVA_HOME="$JAVA11" "$JAVA11/bin/java" -jar "$STREAM_PERF_JAR" "${s_args[@]}" \
      --producers 1 --consumers 0 --rate "$RATE" --size 512 --time "$SECONDS_TO_RUN" \
      > "$here/producer.txt" 2>&1
    sleep 5
    $NS curl -s -m 5 "http://$OWN:8080/metrics" > "$here/consumer_metrics.txt" 2>/dev/null
    wait "$s_consumer" 2>/dev/null
    echo "# the stream consumer instance"
    cat "$here/consumer.txt"
    echo "# the stream consumer's /metrics, read once the producer had finished"
    cat "$here/consumer_metrics.txt"
    stop_own ;;
  stream-perftest-one)
    # RabbitMQ Stream PerfTest as its documentation runs it when nothing else is asked for: one
    # instance, its producer and its consumer in one JVM on one wall clock, at the block's rate and
    # size for the block's minute (freeze 34, S1). Its metrics page is read three seconds before
    # it ends, so that its count of what it kept and its count of what it consumed are read at the
    # same moment.
    here="$(cd "$OUT" && pwd)"
    s_name="sbl-stream-one-$(date +%s)"
    $WRAP env JAVA_HOME="$JAVA11" "$JAVA11/bin/java" -jar "$STREAM_PERF_JAR" \
      --uris "rabbitmq-stream://guest:guest@$BROKER_PRIV:5552" --streams "$s_name" \
      --leader-locator client-local --producers 1 --consumers 1 --rate "$RATE" --size 512 \
      --time "$SECONDS_TO_RUN" --delete-streams --prometheus > "$here/instance.txt" 2>&1 &
    s_one=$!
    OWN_PIDS="$OWN_PIDS $s_one"
    OWN_PATTERN="stream-perf-test\\.jar .*$s_name"
    sleep $((SECONDS_TO_RUN - 3))
    $NS curl -s -m 5 "http://$OWN:8080/metrics" > "$here/consumer_metrics.txt" 2>/dev/null
    wait "$s_one" 2>/dev/null
    echo "# the stream consumer instance"
    cat "$here/instance.txt"
    echo "# the stream consumer's /metrics, read once the producer had finished"
    cat "$here/consumer_metrics.txt"
    stop_own ;;
  pkb)
    # PerfKit Benchmarker's messaging benchmark as PerfKit runs it on its client VM
    # (azure_service_bus.py:79-101): from where its client lies, `python3 -m azure_benchmark`, the
    # end-to-end scenario, its defaults. Its publisher and its receiver are processes its main
    # process starts, one message in flight at a time. On the machine itself in every stage: its
    # broker is a managed service that T1's namespace was never for, and the namespace cannot
    # reach the machine's name resolver. The rest of the wrap -- go-first or a moved clock --
    # reaches all three of its processes, since it starts them itself. Its connection string is
    # read from a file only this user can read, and any key in its output is blanked before the
    # output is kept.
    conn_file="${SBL_PKB_CONNECTION:-$HOME/.pkb_connection}"
    [ -r "$conn_file" ] || { echo "no Service Bus connection string at $conn_file" >&2; exit 3; }
    #: What T2 holds its count against is the messages it is asked for, not the block's minute.
    echo "$PKB_MESSAGES" > "$OUT/asked_to_send.txt"
    pkb_wrap=""
    [ -n "${REST// /}" ] && pkb_wrap="sudo $REST"
    ( cd "$PKB_VM" && $pkb_wrap env PYTHONPATH="$PKB_VM" python3 -m azure_benchmark \
        --topic_name=pkb-topic --subscription_name=pkb-subscription \
        --benchmark_scenario=end_to_end_latency --number_of_messages="$PKB_MESSAGES" \
        --message_size="$PKB_SIZE" --warmup_messages=0 \
        --connection_str="$(cat "$conn_file")" ) 2>&1 \
      | sed -E 's/(SharedAccessKey=)[^;"[:space:]]+/\1<blanked>/g' ;;
  ysb)
    # The Yahoo Streaming Benchmark as its stream-bench.sh runs its Flink test (D36-1): a Flink
    # cluster of one JobManager and one TaskManager, its job, its generator emitting ad events into
    # Kafka at its default rate for the test's time, then the generator's own collection, from
    # Redis, of each campaign window's last update into updated.txt. The TaskManager subtracts --
    # its flusher writes System.currentTimeMillis() as a window's time_updated each second, and the
    # window's start is the event time the generator wrote -- so the rest of the wrap reaches it
    # alone. Its configuration is the one it ships but for where its servers are: the Kafka 3.9.1
    # broker, because its generator speaks Kafka 0.8.2's protocol (D36-2), and the broker's Redis,
    # which the generator's new setup clears first, as stream-bench.sh's does.
    here="$(cd "$OUT" && pwd)"
    #: Its generator writes to "ad-events" whatever its configuration says (core.clj:98 and :202),
    #: so that is the topic, deleted and made again before each run so that no run's job reads
    #: another's events: in the pilot of 11 October a topic named for the run stayed empty while
    #: the generator filled one the broker made for it.
    y_topic="ad-events"
    y_jar=$(ls "$YSB_HOME"/data/target/uberjar/setup-*-standalone.jar 2>/dev/null | head -1)
    mkdir -p "$here/flink-conf" "$here/flink-log"
    cp "$FLINK_HOME/conf/"* "$here/flink-conf/"
    #: The TaskManager is told its address. Left to find it, it connects to the JobManager or falls
    #: back to resolving the machine's name, and in the receiver's namespace the machine's resolver
    #: is out of reach: in the pilot of 11 October it gave up, and the job waited for slots that
    #: never came while the generator ran for two minutes into a topic nobody read.
    printf 'taskmanager.host: %s\n' "$OWN" >> "$here/flink-conf/flink-conf.yaml"
    printf 'kafka.brokers:\n    - "%s"\nzookeeper.servers:\n    - "%s"\nkafka.port: 19094\nzookeeper.port: 2181\nredis.host: "%s"\nkafka.topic: "%s"\nkafka.partitions: 1\nprocess.hosts: 1\nprocess.cores: 4\n' \
      "$BROKER_PRIV" "$BROKER_PRIV" "$BROKER_PRIV" "$y_topic" > "$here/benchmarkConf.yaml"
    "$KAFKA_HOME/bin/kafka-topics.sh" --bootstrap-server "$KAFKA39" --delete --topic "$y_topic" \
      > "$here/topic.txt" 2>&1
    y_wait=0
    while "$KAFKA_HOME/bin/kafka-topics.sh" --bootstrap-server "$KAFKA39" --list 2>/dev/null \
          | grep -qx "$y_topic" && [ "$y_wait" -lt 30 ]; do
      sleep 1; y_wait=$((y_wait + 1))
    done
    "$KAFKA_HOME/bin/kafka-topics.sh" --bootstrap-server "$KAFKA39" --create --topic "$y_topic" \
      --partitions 1 --replication-factor 1 >> "$here/topic.txt" 2>&1
    ( cd "$here" && "$JAVA11/bin/java" -Xmx8g -server -jar "$y_jar" -n \
        --configPath "$here/benchmarkConf.yaml" ) > "$here/new_setup.txt" 2>&1
    y_env=(env JAVA_HOME="$JAVA11" FLINK_CONF_DIR="$here/flink-conf" FLINK_LOG_DIR="$here/flink-log")
    #: Its two JVMs carry this run's configuration folder on their command lines, and the pattern
    #: is anchored at the JVM's own path, which no sudo or pkill command line begins with.
    OWN_PATTERN="^[^ ]*/java .*--configDir $here/flink-conf"
    $NS "${y_env[@]}" "$FLINK_HOME/bin/jobmanager.sh" start-foreground > "$here/jobmanager.txt" 2>&1 &
    OWN_PIDS="$OWN_PIDS $!"
    #: Each started once the one before it answers, up to a minute each.
    y_wait=0
    until $NS bash -c "echo > /dev/tcp/$OWN/6123" 2>/dev/null || [ "$y_wait" -ge 60 ]; do
      sleep 1; y_wait=$((y_wait + 1))
    done
    $NS $REST "${y_env[@]}" "$FLINK_HOME/bin/taskmanager.sh" start-foreground \
      > "$here/taskmanager.txt" 2>&1 &
    OWN_PIDS="$OWN_PIDS $!"
    y_wait=0
    until $NS curl -s -m 2 "http://$OWN:8081/taskmanagers" 2>/dev/null | grep -q '"slotsNumber"' \
          || [ "$y_wait" -ge 60 ]; do
      sleep 1; y_wait=$((y_wait + 1))
    done
    $NS curl -s -m 2 "http://$OWN:8081/taskmanagers" > "$here/taskmanagers.json" 2>/dev/null
    $NS "${y_env[@]}" "$FLINK_HOME/bin/flink" run -d \
      "$YSB_HOME"/flink-benchmarks/target/flink-benchmarks-0.1.0.jar \
      --confPath "$here/benchmarkConf.yaml" > "$here/submit.txt" 2>&1
    sleep 10
    #: As `lein run -r` would start it: the generator's own JVM options from its project file.
    $NS "$JAVA11/bin/java" -Xmx8g -server -jar "$y_jar" -r -t "$YSB_LOAD" \
      --configPath "$here/benchmarkConf.yaml" > "$here/load.txt" 2>&1 &
    y_load=$!
    sleep "$YSB_TEST_TIME"
    sudo pkill -f -- "^[^ ]*/java -Xmx8g -server -jar $y_jar -r " 2>/dev/null
    wait "$y_load" 2>/dev/null
    #: stream-bench.sh collects as soon as the generator stops; five seconds let the windows the
    #: last events fell into take their last update, a flush a second, before they are read.
    sleep 5
    ( cd "$here" && "$JAVA11/bin/java" -Xmx8g -server -jar "$y_jar" -g \
        --configPath "$here/benchmarkConf.yaml" ) > "$here/get_stats.txt" 2>&1
    $NS "${y_env[@]}" "$FLINK_HOME/bin/flink" list > "$here/jobs.txt" 2>&1
    stop_own
    sleep 2
    sudo pkill -9 -f -- "^[^ ]*/java .*--configDir $here/flink-conf" 2>/dev/null
    #: What T2 holds the count it kept against is the windows it wrote for its notebook to read,
    #: not the events: its notebook counts windows.
    grep -c . "$here/updated.txt" > "$OUT/asked_to_send.txt" 2>/dev/null
    echo "# the generator's updated.txt"
    cat "$here/updated.txt" 2>/dev/null
    echo "# the generator's seen.txt"
    cat "$here/seen.txt" 2>/dev/null
    true ;;
  mqtt-benchmark)
    # mqtt-benchmark at f46efba1 (D38-2). Its model is many clients, each publishing once a
    # second -- its interval between a client's messages is in whole seconds -- so the block's
    # rate is RATE clients, each sending the block's minute of messages, started across one
    # second. One process: each client times publish to acknowledgment (QoS 1, its default) in one
    # goroutine on Go's monotonic clock, and its results come out as one JSON document.
    $WRAP mqtt-benchmark -broker "tcp://$MQTT_HOST:1883" -topic "sbl/mqttb/$(date -u +%s%N)" \
      -clients "$RATE" -count "$SECONDS_TO_RUN" -size 512 -qos 1 -message-interval 1 \
      -ramp-up-time 1 -format json -quiet ;;
  sarama-producer-perf)
    # Sarama's kafka-producer-performance at 36f7a14e (D38-2), on its own defaults but the load:
    # an asynchronous producer, acknowledgment from the leader, and its assumed Kafka version,
    # 0.8.2.0, which is why it speaks to the 3.9.1 broker; 512-byte messages, RATE a second, which
    # it sends together at each second's tick; a topic of one partition made for the run.
    s_topic="sbl-sarama-$(date -u +%s%N)"
    "$KAFKA_HOME/bin/kafka-topics.sh" --bootstrap-server "$KAFKA39" --create --topic "$s_topic" \
      --partitions 1 --replication-factor 1 > "$OUT/topic.txt" 2>&1
    $WRAP kafka-producer-performance -brokers "$KAFKA39" -topic "$s_topic" \
      -message-load $((RATE * SECONDS_TO_RUN)) -message-size 512 -throughput "$RATE" ;;
  sbk)
    # SBK 10.8 at 39af60da (D38-2): its Kafka driver with one writer and one reader in one
    # process, Write_Reading, the one mode in which it times a message end to end -- a reader on
    # its own times its poll (KafkaReader.recordRead). RATE records a second for the block's
    # length: with -seconds given and its throughput left at its default, -1, -records is each
    # writer's rate (SbkParameters: throughput < 0 and seconds set). Its help reads a throughput of
    # 0 as "writes 'records'", and in the pilot of 11 October 0 lifted the limit instead: 256,280
    # records a second, every latency the queue's. Its default time unit, whole milliseconds of
    # the wall clock. The topic, of one partition, is made before it starts, as for the other
    # tools: made by SBK itself, its writer met the topic before the broker served it. One JVM, so
    # the whole wrap is on it.
    b_topic="sbl-sbk-$(date -u +%s%N)"
    "$KAFKA_HOME/bin/kafka-topics.sh" --bootstrap-server "$KAFKA" --create --topic "$b_topic" \
      --partitions 1 --replication-factor 1 > "$OUT/topic.txt" 2>&1
    $WRAP env JAVA_HOME="$JAVA25" "$SBK_HOME/build/install/sbk/bin/sbk" -class kafka \
      -broker "$KAFKA" -topic "$b_topic" -writers 1 -readers 1 -size 512 -records "$RATE" \
      -seconds "$SECONDS_TO_RUN" ;;
  kgo-repeater)
    # Redpanda's kgo-repeater at 6567f2f5 (D38-2): two repeaters, each run as its README runs one,
    # on two machines. A, on the broker, produces about RATE messages a second of 512 bytes and
    # echoes what it consumes, stamping every send with the broker's wall clock. B, here, in remote
    # mode in a group of its own, is never activated: it consumes everything A sends and subtracts
    # A's stamp from its own wall clock. The wrap -- the namespace, go-first, or this machine's
    # stepped clock -- is on B, the process that subtracts. B's figures are reset once A has run
    # ten seconds, and read from its /status after the block's minute, before either stops.
    k_topic="sbl-kgo-$(date -u +%s%N)"
    "$KAFKA_HOME/bin/kafka-topics.sh" --bootstrap-server "$KAFKA" --create --topic "$k_topic" \
      --partitions 1 --replication-factor 1 > "$OUT/topic.txt" 2>&1
    k_ssh=(ssh -n -i "$SSH_KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new "ubuntu@$BROKER_PRIV")
    OWN_PATTERN="kgo-repeater .*-topic $k_topic"
    $NS $REST kgo-repeater -brokers "$KAFKA" -topic "$k_topic" -group "b-$k_topic" -workers 1 \
      -payload-size 512 -remote -remote-port 7884 > "$OUT/repeater_b.txt" 2>&1 &
    OWN_PIDS="$OWN_PIDS $!"
    sleep 5
    "${k_ssh[@]}" "nohup kgo-repeater -brokers $KAFKA -topic $k_topic -group a-$k_topic -workers 1 \
      -payload-size 512 -rate-limit-bps $((RATE * 512)) > /tmp/$k_topic.txt 2>&1 < /dev/null &"
    sleep 10
    $NS curl -s -m 5 "http://$OWN:7884/reset" > /dev/null
    sleep "$SECONDS_TO_RUN"
    echo "# kgo-repeater B's /status, read at the end of the run"
    $NS curl -s -m 5 "http://$OWN:7884/status"
    echo
    "${k_ssh[@]}" "pkill -f -- 'kgo-repeater .*-topic $k_topic'; sleep 2; cat /tmp/$k_topic.txt; rm -f /tmp/$k_topic.txt" \
      > "$OUT/repeater_a.txt" 2>&1
    stop_own ;;
  artemis-perf)
    # Artemis 2.57.0's perf client (D39-2), its producer and its consumer as the separate processes
    # its documentation runs them as, from an instance's own bin/artemis, against the broker's
    # Artemis on 61616: the consumer first, then the producer with 512-byte messages at RATE a
    # second, the block's count, non-persistent as by default, with the confirmation window its
    # documentation gives. The consumer stamps its receipt with its own clock and subtracts the
    # producer's, so the rest of the wrap is on it alone. Its queue is purged first, so that no
    # message an earlier run rolled back is delivered into this one.
    here="$(cd "$OUT" && pwd)"
    a_url="tcp://$BROKER_PRIV:61616"
    env JAVA_HOME="$JAVA17" "$ARTEMIS_CLIENT/bin/artemis" queue purge --name TEST --url "$a_url" \
      --user sbl --password sbl --silent > "$here/purge.txt" 2>&1
    OWN_PATTERN="perf consumer .*$here/consumer.json"
    $NS $REST env JAVA_HOME="$JAVA17" "$ARTEMIS_CLIENT/bin/artemis" perf consumer --url "$a_url" \
      --duration $((SECONDS_TO_RUN + 20)) --show-latency --json "$here/consumer.json" \
      --hdr "$here/consumer.hdr" queue://TEST > "$here/consumer.txt" 2>&1 &
    a_consumer=$!
    OWN_PIDS="$OWN_PIDS $a_consumer"
    sleep 5
    #: Stopped by `timeout` twenty seconds past the block's minute if it has not stopped itself. In
    #: the pilots of 11 October, under S1's steps, its producer stopped sending after ten messages,
    #: printed no error, and waited for the rest of its count: its own --duration did not end it,
    #: and the run's limit stopped the shell around it but left the JVM running. `timeout` signals
    #: the JVM itself.
    timeout -k 10 $((SECONDS_TO_RUN + 20)) env JAVA_HOME="$JAVA17" "$ARTEMIS_CLIENT/bin/artemis" \
      perf producer --url "$a_url?confirmationWindowSize=20000" --message-size 512 --rate "$RATE" \
      --message-count $((RATE * SECONDS_TO_RUN)) --json "$here/producer.json" queue://TEST \
      > "$here/producer.txt" 2>&1
    wait "$a_consumer" 2>/dev/null
    stop_own
    echo "# artemis perf consumer's console"
    cat "$here/consumer.txt"
    echo "# artemis perf consumer's JSON"
    cat "$here/consumer.json" 2>/dev/null
    echo
    echo "# artemis perf producer's JSON"
    cat "$here/producer.json" 2>/dev/null
    echo ;;
  rocketmq-benchmark)
    # RocketMQ 5.5.1's benchmark (D39-2): its Consumer and its Producer, two JVMs, launched as its
    # bin/tools.sh launches its example classes -- its benchmark scripts pass a Java 8 option that
    # Java 17 refuses -- with that script's class path and heap. The Producer has no rate of its
    # own: each of its threads sends and waits for the reply, so one thread runs at one message per
    # round trip, and it stops at the block's count. The Consumer subtracts each message's born time,
    # the producer's clock, from its own, so the rest of the wrap is on it alone; it prints every ten
    # seconds and never ends, so it is read once its report after the last message is out.
    here="$(cd "$OUT" && pwd)"
    r_ns="$BROKER_PRIV:9876"
    r_topic="sbl-rmq-$(date -u +%s%N)"
    r_cp=".:$ROCKETMQ_HOME/conf:$ROCKETMQ_HOME/lib/*"
    r_jopt="-server -Xms1g -Xmx1g -Xmn256m -XX:MetaspaceSize=128m -XX:MaxMetaspaceSize=128m"
    env JAVA_HOME="$JAVA17" ROCKETMQ_HOME="$ROCKETMQ_HOME" sh "$ROCKETMQ_HOME/bin/mqadmin" updateTopic \
      -n "$r_ns" -c DefaultCluster -t "$r_topic" -r 1 -w 1 > "$here/topic.txt" 2>&1
    OWN_PATTERN="benchmark.Consumer .*-t $r_topic"
    # shellcheck disable=SC2086
    $NS $REST "$JAVA17/bin/java" $r_jopt -cp "$r_cp" org.apache.rocketmq.example.benchmark.Consumer \
      -n "$r_ns" -t "$r_topic" -g "sbl-$r_topic" > "$here/consumer.txt" 2>&1 &
    OWN_PIDS="$OWN_PIDS $!"
    sleep 10
    # shellcheck disable=SC2086
    timeout 300 "$JAVA17/bin/java" $r_jopt -Dorg.apache.rocketmq.client.sendSmartMsg=true -cp "$r_cp" \
      org.apache.rocketmq.example.benchmark.Producer -n "$r_ns" -t "$r_topic" -s 512 -w 1 \
      -q $((RATE * SECONDS_TO_RUN)) > "$here/producer.txt" 2>&1
    sleep 25
    stop_own
    echo "# rocketmq benchmark consumer's console"
    cat "$here/consumer.txt"
    echo "# rocketmq benchmark producer's console"
    cat "$here/producer.txt" ;;
  bookkeeper-benchmark)
    # BookKeeper 4.18.1's benchmark (D39-2), `bin/benchmark writes`, one process, against the three
    # bookies and the ZooKeeper `server36 up bookkeeper` starts: 512-byte entries, the ensemble and
    # quorums of its defaults, no warm-up, for the block's length, and -throttle at RATE. That flag
    # is its only way to set a rate: the client's limiter takes it as permits a second, and blocks
    # inside the call the benchmark times (LedgerHandle.java:249-250, 1716-1718;
    # BenchThroughputLatency.java:187-188). It dumps every latency it kept, which is read with its log.
    here="$(cd "$OUT" && pwd)"
    $WRAP env JAVA_HOME="$JAVA17" PATH="$JAVA17/bin:/usr/bin:/bin" BENCHMARK_EXTRA_OPTS="-Xms64m -Xmx256m" \
      "$BOOKKEEPER_HOME/bin/benchmark" writes -zookeeper "$BROKER_PRIV:2181" -ensemble 3 -quorum 2 \
      -ackQuorum 2 -entrysize 512 -throttle "$RATE" -time "$SECONDS_TO_RUN" -sendlimit 10000 \
      -skipwarmup -latencyFile "$here/latencyDump.dat"
    echo "# bookkeeper benchmark's latency dump"
    cat "$here/latencyDump.dat" 2>/dev/null ;;
  *)
    echo "no such tool here: $TOOL" >&2; exit 2 ;;
esac
