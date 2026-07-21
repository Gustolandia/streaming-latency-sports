#!/usr/bin/env bash
# Network-realism sweep: inject one-way egress delay on BOTH broker containers with tc netem
# and re-measure. Producer/consumer/broker are co-located on one host, so transport is ~1 ms
# loopback; a reviewer may object that this says nothing about a networked deployment. A delay
# applied equally to both backends should raise both and leave the equivalence intact.
#
# tc is run from a NET_ADMIN sidecar sharing each broker's network namespace, because the
# broker images do not ship iproute2.
set -u
PLANS=data/processed/replay_plans/3bfbffe1de5750ebd47d770be0bb924a10cde54f
FB=data/processed/replay_plans/s2sf12/combined_plan.csv
MANIFEST=runs/_netem_prefixes.txt
: > "$MANIFEST"

netem() {  # $1=container $2=action(add|change|del) $3=delay_ms
  if [ "$2" = "del" ]; then
    docker run --rm --cap-add=NET_ADMIN --network="container:$1" alpine:3.19 \
      sh -c "apk add --no-cache iproute2 >/dev/null 2>&1; tc qdisc del dev eth0 root 2>/dev/null" >/dev/null 2>&1
  else
    docker run --rm --cap-add=NET_ADMIN --network="container:$1" alpine:3.19 \
      sh -c "apk add --no-cache iproute2 >/dev/null 2>&1; tc qdisc replace dev eth0 root netem delay $3ms" >/dev/null 2>&1
  fi
}

for D in 0 5 20 50; do
  echo "===== NETEM delay=${D}ms $(date +%H:%M:%S) ====="
  if [ "$D" -gt 0 ]; then
    netem broker add "$D"; netem streaming-latency-sports-redis-1 add "$D"
  else
    netem broker del; netem streaming-latency-sports-redis-1 del
  fi
  OUT=$(python scripts/run_concurrency_test.py 5 "$FB" 3 --plans-dir "$PLANS" \
        --speedup 1 --max-t-sim 9000 --trial-timeout 600 \
        --kafka-bootstrap localhost:19092 --redis-host localhost --redis-port 16379 \
        --kafka-producer-extra "--max-inflight 64" 2>&1)
  echo "$OUT" | grep -E "^Prefix:|Successful|Failed" || true
  PREFIX=$(echo "$OUT" | grep -oE 'concurrency_n5_[0-9]{8}_[0-9]{6}' | head -1)
  echo "${D} ${PREFIX}" >> "$MANIFEST"
done

# always clear the shaping, even if a run failed
netem broker del; netem streaming-latency-sports-redis-1 del
echo "===== NETEM SWEEP DONE $(date +%H:%M:%S) ====="
