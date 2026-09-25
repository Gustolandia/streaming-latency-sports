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
  *)
    echo "no such tool here: $TOOL" >&2; exit 2 ;;
esac
