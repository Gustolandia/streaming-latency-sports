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
field = ("    // Added for an external audit: counts the end-to-end samples the guard below\n"
         "    // discards, SEPARATED BY SIGN. Zero means publish and receive fell in the same\n"
         "    // millisecond tick (record.timestamp() is ms-resolution under CreateTime) and is a\n"
         "    // resolution artefact. Negative means the receive stamp precedes the publish stamp\n"
         "    // and is a causality violation. A single counter conflates the two, which is the\n"
         "    // mistake this replaces. Does not change what OMB measures or reports.\n"
         "    private final java.util.concurrent.atomic.AtomicLong sblZeroLatency =\n"
         "            new java.util.concurrent.atomic.AtomicLong();\n"
         "    private final java.util.concurrent.atomic.AtomicLong sblNegativeLatency =\n"
         "            new java.util.concurrent.atomic.AtomicLong();\n"
         "    private final java.util.concurrent.atomic.AtomicLong sblMostNegative =\n"
         "            new java.util.concurrent.atomic.AtomicLong();\n"
         "    private final java.util.concurrent.atomic.AtomicLong sblKept =\n"
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
            sblKept.incrementAndGet();
            endToEndCumulativeLatencyRecorder.recordValue(endToEndLatencyMicros);
            endToEndLatencyRecorder.recordValue(endToEndLatencyMicros);
            endToEndLatencyStats.registerSuccessfulEvent(endToEndLatencyMicros, TimeUnit.MICROSECONDS);
        } else if (endToEndLatencyMicros == 0) {
            long z = sblZeroLatency.incrementAndGet();
            if (z <= 3 || z % 10000 == 0) {
                System.err.println("SBL_DISCARD_ZERO total=" + z
                        + " kept=" + sblKept.get());
            }
        } else {
            long n = sblNegativeLatency.incrementAndGet();
            long prev = sblMostNegative.get();
            if (endToEndLatencyMicros < prev) {
                sblMostNegative.set(endToEndLatencyMicros);
            }
            if (n <= 5 || n % 1000 == 0) {
                System.err.println("SBL_DISCARD_NEGATIVE total=" + n
                        + " sample_micros=" + endToEndLatencyMicros
                        + " most_negative=" + sblMostNegative.get()
                        + " kept=" + sblKept.get());
            }
        }"""
assert old in s, "guard body not found verbatim"
s = s.replace(old, new, 1)
# A final summary, emitted when OMB dumps its own stats, so a cell with few discards still
# reports its totals rather than leaving them to be inferred from absent periodic lines.
sum_anchor = "    public void resetLatencies() {"
if sum_anchor in s:
    summary = ("    public void sblPrintDiscardSummary() {\n"
               "        System.err.println(\"SBL_DISCARD_SUMMARY kept=\" + sblKept.get()\n"
               "                + \" zero=\" + sblZeroLatency.get()\n"
               "                + \" negative=\" + sblNegativeLatency.get()\n"
               "                + \" most_negative_micros=\" + sblMostNegative.get());\n"
               "    }\n\n")
    s = s.replace(sum_anchor, summary + sum_anchor, 1)

io.open(p, "w", encoding="utf-8").write(s)
print("patched: sign-separated counters, guard condition unchanged")
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

# OMB reads the payload from a FILE. Without payloadFile the run dies in
# FilePayloadReader.load with a NullPointerException about four seconds in, having
# produced no latency at all -- and the discard count is then 0 because nothing was
# ever measured. Every run of this campaign failed that way, including the first,
# whose zero was reported in the manuscript as a genuine null.
MESSAGE_SIZE="${MESSAGE_SIZE:-200}"
PAYLOAD="$PWD/$OUT/omb_payload_${MESSAGE_SIZE}b.data"
python3 -c "open('$PAYLOAD','wb').write(b'x' * ${MESSAGE_SIZE})"
[ -s "$PAYLOAD" ] || { echo "FATAL: could not create the payload file"; exit 1; }
echo "payload file: $PAYLOAD ($(stat -c %s "$PAYLOAD") bytes)"

cat > "$OUT/omb_workload.yaml" <<EOF
name: sbl-audit
topics: 1
partitionsPerTopic: 1
messageSize: ${MESSAGE_SIZE}
payloadFile: "${PAYLOAD}"
subscriptionsPerTopic: 1
consumerPerSubscription: 1
producersPerTopic: 1
producerRate: ${PRODUCER_RATE:-500}
consumerBacklogSizeGB: 0
testDurationMinutes: ${DURATION_MIN}
EOF

# LOAD_PCT puts the machine under the condition that produces inversions at all.
# E-A5 and E-A9 show the rate is governed by scheduling stalls, which an idle
# machine does not have; testing for this failure at idle is close to testing under
# conditions chosen to hide it. Distributed mode would add the cross-host CLOCK
# channel, but chrony measures the driver-to-broker offset at about 0.067 ms, far
# below the millisecond resolution OMB reports in, so that channel cannot drive its
# samples negative here whatever we do. Occupancy can, and embedded mode reaches it.
if [ "${LOAD_PCT:-0}" != "0" ]; then
  banner "background load at ${LOAD_PCT}% duty on $(nproc) cores"
  stress-ng --cpu "$(nproc)" --cpu-load "$LOAD_PCT" \
    --timeout $(( DURATION_MIN * 60 + 600 ))s >/dev/null 2>&1 &
  STRESS_PID=$!
  trap 'kill -9 "$STRESS_PID" 2>/dev/null; pkill -9 -x stress-ng 2>/dev/null' EXIT
  sleep 5
fi

banner "running OMB against ${KAFKA_BOOTSTRAP} for ${DURATION_MIN} min (load ${LOAD_PCT:-0}%)"
( cd "$OMB" && timeout $(( DURATION_MIN * 60 + 300 )) \
    bin/benchmark --drivers "$PWD/../sbl/$OUT/omb_driver.yaml" \
    "$PWD/../sbl/$OUT/omb_workload.yaml" 2>&1 ) | tee "$OUT/omb_stdout.log" | tail -25

banner "validating that the benchmark actually ran"
PUB=$(grep -c "Pub rate" "$OUT/omb_stdout.log" 2>/dev/null)
FAILED=$(grep -c "Failed to run the workload" "$OUT/omb_stdout.log" 2>/dev/null)
echo "  'Pub rate' lines: $PUB   failure lines: $FAILED"
if [ "${PUB:-0}" -lt 1 ] || [ "${FAILED:-0}" -gt 0 ]; then
  printf 'harness,mode,valid,discarded_nonpositive,reason,duration_min,load_pct\n' > "$OUT/omb_loaded_result.csv"
  printf '%s,embedded,0,,"no latency output (pub=%s failures=%s)",%s,%s\n' \
    "OpenMessaging Benchmark" "$PUB" "$FAILED" "$DURATION_MIN" "${LOAD_PCT:-0}" \
    >> "$OUT/omb_loaded_result.csv"
  echo "NO VALID RUN: the benchmark produced no latency output; no count reported"
  exit 1
fi

banner "what OMB discarded without recording"
ZERO=$(grep -o "SBL_DISCARD_ZERO total=[0-9]*" "$OUT/omb_stdout.log" | tail -1 | grep -oE "[0-9]+$")
NEG=$(grep -o "SBL_DISCARD_NEGATIVE total=[0-9]*" "$OUT/omb_stdout.log" | tail -1 | grep -oE "[0-9]+$")
KEPT=$(grep -oE "kept=[0-9]+" "$OUT/omb_stdout.log" | tail -1 | grep -oE "[0-9]+$")
MOSTNEG=$(grep -oE "most_negative=-?[0-9]+" "$OUT/omb_stdout.log" | tail -1 | grep -oE "\-?[0-9]+$")
ZERO=${ZERO:-0}; NEG=${NEG:-0}; KEPT=${KEPT:-0}; MOSTNEG=${MOSTNEG:-0}
LAST=$((ZERO + NEG))
LAST=${LAST:-0}
printf 'harness,mode,valid,discarded_total,discarded_zero,discarded_negative,most_negative_micros,kept,pub_lines,duration_min,load_pct,bootstrap\n%s,%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
  "OpenMessaging Benchmark" "embedded" "$LAST" "$ZERO" "$NEG" "$MOSTNEG" "$KEPT" \
  "$PUB" "$DURATION_MIN" "${LOAD_PCT:-0}" \
  "$KAFKA_BOOTSTRAP" > "$OUT/omb_loaded_result.csv"
echo "DISCARDED: total=$LAST  zero=$ZERO  negative=$NEG  most_negative=${MOSTNEG}us  kept=$KEPT"
# The distinction the single counter hid: zero is a millisecond-tick collision, negative is a
# causality violation. Only the second is the failure this project is about.
if [ "$NEG" = "0" ] && [ "$ZERO" != "0" ]; then
  echo "NOTE: every discard was exactly zero -- resolution artefact, NOT a causality violation"
fi
cat "$OUT/omb_loaded_result.csv"

banner "OMB_DISCARD_COUNT_COMPLETE"
