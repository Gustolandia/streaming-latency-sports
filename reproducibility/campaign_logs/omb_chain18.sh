#!/usr/bin/env bash
# Chain 18 -- the referee campaign. Every runnable item from the simulated TPDS/TC report.
#
# Predictions registered before any cell runs. Falsifiers inline.
#
# BLOCK A -- same-host Python harness (referee M1, strongest form: no JVM anywhere).
#   guard_harness.py implements exactly the pattern: ms-quantised stamps, positive guard, paced
#   producer, one clock (producer and consumer both on the driver; Redis on the broker host).
#   Prediction: the grid law is the pattern's, not the stack's -- 500/s (q=1) bimodal near
#   {0,100}; 300/s (q=3) on the thirds grid or full-width; 457/s (incommensurate) stable at the
#   harness's own theta, which that arm measures. Falsifier: the q=1 arm unimodal mid-scale, or
#   the incommensurate arm bimodal. The harness also RECORDS its pacer jitter per run (referee
#   M3): the kernel account predicts arm class from measured jitter against cell width tau/q,
#   and that consistency is testable for the first time because jitter is finally an observable.
#
# BLOCK B -- cross-host Python harness (referee M2: the case OMB's distributed mode never let us
#   measure). Producer on the driver stamps with the driver's clock; consumer runs on the broker
#   host and stamps with the broker's clock; both chrony-disciplined, measured offset ~0.067 ms.
#   Prediction: ZERO negative differences (offset << T_true), and the same grid classes as A at
#   the cross-host theta. Falsifier that would MATTER: any negative at rest -- it would be the
#   first observed cross-clock inversion in this study and would change Section 6.8's status
#   from source-audit to measurement in the other direction. Either outcome is the measurement
#   the referee asked for.
#
# BLOCK C -- OMB Redis driver (referee M1, cheapest form: different client code path, same
#   framework guard). Prediction: same class structure at the Redis path's theta -- q=1
#   all-or-nothing, incommensurate stable, q=3 on the thirds grid. Falsifier: classes absent.
#
# BLOCK D -- controlled alternation (referee M7). chain17 saw 300/s smear in the evening while
#   625/s held cleanly 40 minutes later; passes were hours apart, so epoch and arm are
#   confounded. Here the two arms interleave A/B/A/B within one session: (300, 625) x 4 pairs.
#   If the contrast is arm-coupled it survives interleaving; if epoch-coupled the arms co-vary.
#   Registered: no point prediction -- this is the experiment that decides, and both outcomes
#   are reportable.
#
# BLOCK E -- OMB distributed mode, three further attempts with full diagnostics captured
#   (referee M2): version recorded, coordinator and worker logs kept whole, failure signature
#   extracted per attempt. No prediction; documentation the report asked for.
set -u
cd ~/sbl || exit 1

BROKER=10.0.1.221
guard () {
  local fb db
  fb=$(ssh -i ~/.ssh/oci_sbl -o ConnectTimeout=10 -o BatchMode=yes -o StrictHostKeyChecking=no \
        ubuntu@$BROKER "df --output=avail -BG / | tail -1 | tr -dc '0-9'" 2>/dev/null)
  [ "${fb:-0}" -ge 5 ] || { echo "[guard] broker disk low"; return 1; }
  db=$(df --output=avail -BG / | tail -1 | tr -dc '0-9')
  [ "${db:-0}" -ge 5 ] || { echo "[guard] driver disk low"; return 1; }
}

hcell () {  # hcell CAMPAIGN NAME RATE XHOST(0|1)
  local camp=$1 name=$2 rate=$3 xhost=$4
  guard || exit 1
  local out=docs/results/external/$camp/$name
  mkdir -p "$out"
  local stream="gh:$camp:$name"
  python3 -c "import redis; redis.Redis(host='$BROKER').delete('$stream')"
  if [ "$xhost" = "1" ]; then
    ssh -i ~/.ssh/oci_sbl -o BatchMode=yes -o StrictHostKeyChecking=no ubuntu@$BROKER \
      "python3 ~/guard_harness.py --role consumer --redis-host 127.0.0.1 --stream '$stream' --idle-exit 40" \
      > "$out/consumer.json" 2>"$out/consumer.err" &
  else
    python3 ~/guard_harness.py --role consumer --redis-host $BROKER --stream "$stream" \
      --idle-exit 40 > "$out/consumer.json" 2>"$out/consumer.err" &
  fi
  local cpid=$!
  sleep 3
  python3 ~/guard_harness.py --role producer --redis-host $BROKER --stream "$stream" \
    --rate "$rate" --duration 180 > "$out/producer.json" 2>"$out/producer.err"
  wait $cpid
  python3 - "$out" "$camp" "$name" "$rate" "$xhost" <<'PYEOF'
import json, sys, os
out, camp, name, rate, xhost = sys.argv[1:6]
res = {"campaign": camp, "cell": name, "rate": float(rate), "cross_host": xhost == "1"}
for part in ("producer", "consumer"):
    with open(os.path.join(out, part + ".json"), encoding="utf-8") as fh:
        res[part] = json.load(fh)
with open(os.path.join(out, "harness_result.json"), "w", encoding="utf-8") as fh:
    json.dump(res, fh)
c = res["consumer"]; seen = c["kept"] + c["discarded_zero"] + c["discarded_negative"]
print("  [%s/%s] kept=%d zero=%d NEG=%d retention=%.2f%% jitter_p90=%.0fus" % (
    camp, name, c["kept"], c["discarded_zero"], c["discarded_negative"],
    100.0 * c["kept"] / seen if seen else 0.0, res["producer"]["jitter_us"]["p90"]))
PYEOF
}

ocell () {  # ocell CAMPAIGN NAME RATE DRIVER
  local camp=$1 name=$2 rate=$3 drv=$4
  guard || exit 1
  local out=docs/results/external/$camp/$name
  mkdir -p "$out"
  MESSAGE_SIZE=200 PRODUCER_RATE=$rate LOAD_PCT=0 OUT="$out" DURATION_MIN=3 WARMUP_MIN=0 \
    DRIVER=$drv timeout -k 60 1800 bash cloud/campaigns/omb_discard_count.sh 2>&1 | tail -2
  echo "  [$camp/$name] driver=$drv rate=$rate $(date -u +%H:%MZ)"
}

collect () {
  python3 - <<'PYEOF'
import csv, json, os
root = "docs/results/external"
rows = []
for camp in ("harness_local", "harness_xhost"):
    d = os.path.join(root, camp)
    if not os.path.isdir(d):
        continue
    for cell in sorted(os.listdir(d)):
        p = os.path.join(d, cell, "harness_result.json")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as fh:
            r = json.load(fh)
        c, pr = r["consumer"], r["producer"]
        seen = c["kept"] + c["discarded_zero"] + c["discarded_negative"]
        rows.append({
            "campaign": r["campaign"], "cell": r["cell"], "rate_hz": int(r["rate"]),
            "cross_host": r["cross_host"], "sent": pr["sent"], "kept": c["kept"],
            "discarded_zero": c["discarded_zero"],
            "discarded_negative": c["discarded_negative"],
            "retention_pct": round(100.0 * c["kept"] / seen, 4) if seen else "",
            "jitter_p50_us": round(pr["jitter_us"]["p50"], 1),
            "jitter_p90_us": round(pr["jitter_us"]["p90"], 1),
            "jitter_p99_us": round(pr["jitter_us"]["p99"], 1),
            "truncated": bool(c.get("truncated")),
        })
with open(os.path.join(root, "harness_results.csv"), "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
print("harness_results.csv: %d rows" % len(rows))
PYEOF
}

echo "[chain18] START $(date -u +%FT%TZ)"
scp -i ~/.ssh/oci_sbl -o BatchMode=yes -o StrictHostKeyChecking=no \
  ~/guard_harness.py ubuntu@$BROKER:~/guard_harness.py

echo "[chain18] === A: same-host Python harness (M1 strongest, M3 pacer) ==="
for R in 1 2 3 4; do hcell harness_local r500_rep$R 500 0; done
for R in 1 2 3 4; do hcell harness_local r300_rep$R 300 0; done
for R in 1 2 3 4; do hcell harness_local r457_rep$R 457 0; done
collect

echo "[chain18] === B: cross-host Python harness (M2 measured) ==="
for R in 1 2 3 4; do hcell harness_xhost r500_rep$R 500 1; done
for R in 1 2 3 4; do hcell harness_xhost r300_rep$R 300 1; done
for R in 1 2 3 4; do hcell harness_xhost r457_rep$R 457 1; done
collect

echo "[chain18] === C: OMB Redis driver (M1 cheapest) ==="
for R in 1 2 3; do ocell ultimate_redis r500_rep$R 500 redis; done
for R in 1 2 3; do ocell ultimate_redis r300_rep$R 300 redis; done
for R in 1 2 3; do ocell ultimate_redis r457_rep$R 457 redis; done

echo "[chain18] === D: A/B/A/B alternation (M7) ==="
for P in 1 2 3 4; do
  ocell ultimate_alt r300_rep$P 300 kafka
  ocell ultimate_alt r625_rep$P 625 kafka
done

echo "[chain18] === E: distributed mode, three diagnosed attempts (M2) ==="
for R in 1 2 3; do
  guard || exit 1
  OUTD=docs/results/external/dist_diag/attempt$R
  mkdir -p "$OUTD"
  ( cd ~/omb && git rev-parse HEAD > ~/sbl/$OUTD/omb_version.txt 2>/dev/null )
  LOAD_PCT=0 OUT="$OUTD" timeout -k 60 1200 bash cloud/campaigns/omb_distributed.sh \
    > "$OUTD/attempt.log" 2>&1
  echo "  [dist_diag/attempt$R] exit=$? signature: $(grep -aoE 'Exception|Error|refused|timed out' "$OUTD"/*.log 2>/dev/null | sort | uniq -c | tr '\n' ' ' | head -c 160)"
done

python3 scripts/index_external_campaigns.py --root docs/results/external \
  --out docs/results/external_campaigns_index.csv 2>&1 | tail -2
echo "[chain18] ALL DONE $(date -u +%FT%TZ)"
