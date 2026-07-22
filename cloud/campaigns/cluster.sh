#!/usr/bin/env bash
# E3: 3-node cluster with each broker node on its OWN host. Co-locating six broker
# containers with the load generator is what confounded the original cluster arm.
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
: "${BROKER2_PRIV:?cluster.sh needs BROKER2_PRIV}"
: "${BROKER3_PRIV:?cluster.sh needs BROKER3_PRIV}"
NODES="$BROKER_PRIV:$REDIS_CLUSTER_PORT,$BROKER2_PRIV:$REDIS_CLUSTER_PORT,$BROKER3_PRIV:$REDIS_CLUSTER_PORT"
banner "cluster N=5 nodes=$NODES"
python3 scripts/run_concurrency_test.py 5 "$PLAN" "${CLUSTER_REPS:-3}" \
  --speedup 10 --max-t-sim 600 \
  --kafka-bootstrap "$KAFKA_CLUSTER_BOOTSTRAP" \
  --redis-host "$BROKER_PRIV" --redis-port "$REDIS_CLUSTER_PORT" \
  --broker-count 3 --cluster-mode --redis-cluster-nodes "$NODES" \
  --plans-dir "$PLANS_DIR" --kafka-producer-extra "$KAFKA_PRODUCER_EXTRA" \
  --trial-timeout 1800 2>&1 | tail -3
banner "CLUSTER_COMPLETE"
