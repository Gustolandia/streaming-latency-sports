#!/usr/bin/env bash
# E-X: run the OpenMessaging Benchmark and count what it silently discards. Referee issue M1.
#
# Section 6.7 reports, from source, that OMB computes a cross-process end-to-end latency and then
# admits it to the histogram only `if (endToEndLatencyMicros > 0)`, with no counter for the rest.
# A referee asked us to APPLY the check to a harness we did not write, and that source finding is
# not the same thing.
#
# It also makes the obvious version of the experiment impossible. You cannot apply a
# causality check to OMB's output, because the violations never reach the output: the guard drops
# them inside the harness. So the only empirical route is to make the discards observable and then
# run the real benchmark.
#
# This script therefore does the minimum that achieves that, and nothing more:
#
#   * it adds ONE counter to WorkerStats.java, incremented in the `else` branch of the existing
#     guard, and logs the total. It does NOT change the latency computation, the guard's
#     condition, or any reported statistic. What OMB measures and reports is untouched; we only
#     make visible a quantity it already computes and throws away.
#   * it then runs OMB unmodified in every other respect against our Kafka broker.
#
# The output is a single number with a clear meaning: how many end-to-end samples the canonical
# broker benchmark discarded without recording, in a run whose reported latency distribution
# looks entirely healthy.
#
# Interpreting the result, stated in advance so it cannot be chosen afterwards:
#   count > 0  -- the failure mode occurs in a harness we did not write, on real hardware, and is
#                 invisible in that harness's own output. This is the strongest form of the M1
#                 evidence.
#   count == 0 -- on this deployment the violation did not occur. That is a real and reportable
#                 negative: it bounds our claim to the conditions where it happens, and we would
#                 say so rather than quietly not reporting the run.
#
# Usage:  nohup bash cloud/campaigns/omb_discard_count.sh > omb_run.log 2>&1 &
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
set +e

OMB="${OMB:-$HOME/omb}"
OUT="${OUT:-docs/results/external}"
DURATION_MIN="${DURATION_MIN:-3}"
mkdir -p "$OUT"

[ -d "$OMB" ] || { echo "FATAL: no OMB checkout at $OMB"; exit 1; }

# OMB enforces Maven >= 3.8.6; Ubuntu ships 3.6.3, which fails the enforcer plugin before
# compiling anything. Prefer an explicitly installed newer Maven when one is present.
MVN="${MVN:-$(command -v /usr/local/bin/mvn || command -v mvn)}"
[ -n "$MVN" ] || { echo "FATAL: maven not installed"; exit 1; }
MVN_VER=$("$MVN" -version 2>/dev/null | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
echo "using maven $MVN_VER at $MVN"
case "$MVN_VER" in
  3.[0-7].*|3.8.[0-5]) echo "FATAL: OMB requires maven >= 3.8.6, found $MVN_VER"; exit 1;;
esac

WS="$OMB/benchmark-framework/src/main/java/io/openmessaging/benchmark/worker/WorkerStats.java"
[ -f "$WS" ] || { echo "FATAL: WorkerStats.java not found"; exit 1; }

banner "OMB discard counter: patching $WS"

# Record exactly what we changed, so the paper can state it and a reader can check it.
cp "$WS" "$OUT/WorkerStats.java.orig"

python3 - "$WS" <<'PY'
import io, sys, re
p = sys.argv[1]
s = io.open(p, encoding="utf-8").read()

if "sblNonPositiveLatency" in s:
    print("already patched"); raise SystemExit(0)

# One counter field, placed with the other private fields.
anchor = "    private final Recorder endToEndLatencyRecorder"
field = ("    // Added for an external audit: counts end-to-end samples the guard below discards.\n"
         "    // Does not change what OMB measures or reports.\n"
         "    private final java.util.concurrent.atomic.AtomicLong sblNonPositiveLatency =\n"
         "            new java.util.concurrent.atomic.AtomicLong();\n\n")
assert anchor in s, "field anchor not found"
s = s.replace(anchor, field + anchor, 1)

# The else branch. The guard's condition is untouched.
old = """        if (endToEndLatencyMicros > 0) {
            endToEndCumulativeLatencyRecorder.recordValue(endToEndLatencyMicros);
            endToEndLatencyRecorder.recordValue(endToEndLatencyMicros);
            endToEndLatencyStats.registerSuccessfulEvent(endToEndLatencyMicros, TimeUnit.MICROSECONDS);
        }"""
new = """        if (endToEndLatencyMicros > 0) {
            endToEndCumulativeLatencyRecorder.recordValue(endToEndLatencyMicros);
            endToEndLatencyRecorder.recordValue(endToEndLatencyMicros);
            endToEndLatencyStats.registerSuccessfulEvent(endToEndLatencyMicros, TimeUnit.MICROSECONDS);
        } else {
            long n = sblNonPositiveLatency.incrementAndGet();
            if (n <= 5 || n % 1000 == 0) {
                System.err.println("SBL_DISCARDED_NONPOSITIVE total=" + n
                        + " sample_micros=" + endToEndLatencyMicros);
            }
        }"""
assert old in s, "guard body not found verbatim"
s = s.replace(old, new, 1)
io.open(p, "w", encoding="utf-8").write(s)
print("patched: one counter, one else branch, guard condition unchanged")
PY
[ $? -eq 0 ] || { echo "FATAL: patch failed"; exit 1; }

diff -u "$OUT/WorkerStats.java.orig" "$WS" > "$OUT/omb_patch.diff"
echo "patch recorded at $OUT/omb_patch.diff"

banner "building OMB (this is CPU-heavy; no latency campaign may be running)"
( cd "$OMB" && "$MVN" -q -B -DskipTests package 2>&1 | tail -20 )
JAR=$(find "$OMB" -name "benchmark-framework-*.jar" -not -name "*sources*" | head -1)
[ -n "$JAR" ] || { echo "FATAL: build produced no jar"; exit 1; }
echo "built: $JAR"

# Minimal driver + workload: OMB's own Kafka driver, pointed at our broker.
cat > "$OUT/omb_driver.yaml" <<EOF
name: Kafka
driverClass: io.openmessaging.benchmark.driver.kafka.KafkaBenchmarkDriver
replicationFactor: 1
topicConfig: |
  min.insync.replicas=1
commonConfig: |
  bootstrap.servers=${KAFKA_BOOTSTRAP}
producerConfig: |
  acks=all
  linger.ms=0
consumerConfig: |
  auto.offset.reset=earliest
  enable.auto.commit=false
EOF

cat > "$OUT/omb_workload.yaml" <<EOF
name: sbl-audit
topics: 1
partitionsPerTopic: 1
messageSize: 200
subscriptionsPerTopic: 1
consumerPerSubscription: 1
producersPerTopic: 1
producerRate: 500
consumerBacklogSizeGB: 0
testDurationMinutes: ${DURATION_MIN}
EOF

banner "running OMB against ${KAFKA_BOOTSTRAP} for ${DURATION_MIN} min"
( cd "$OMB" && timeout $(( DURATION_MIN * 60 + 300 )) \
    bin/benchmark --drivers "$PWD/../sbl/$OUT/omb_driver.yaml" \
    "$PWD/../sbl/$OUT/omb_workload.yaml" 2>&1 ) | tee "$OUT/omb_stdout.log" | tail -25

banner "what OMB discarded without recording"
grep -c "SBL_DISCARDED_NONPOSITIVE" "$OUT/omb_stdout.log" > /dev/null 2>&1
LAST=$(grep -o "SBL_DISCARDED_NONPOSITIVE total=[0-9]*" "$OUT/omb_stdout.log" | tail -1 | grep -o "[0-9]*$")
LAST=${LAST:-0}
printf 'harness,discarded_nonpositive,duration_min,bootstrap\n%s,%s,%s,%s\n' \
  "OpenMessaging Benchmark" "$LAST" "$DURATION_MIN" "$KAFKA_BOOTSTRAP" \
  > "$OUT/omb_discards.csv"
echo "DISCARDED NON-POSITIVE SAMPLES: $LAST"
cat "$OUT/omb_discards.csv"

banner "OMB_DISCARD_COUNT_COMPLETE"
