#!/usr/bin/env bash
# Start one cluster node per host, then form both clusters.
#   On each host:  sudo bash cluster_brokers.sh node <NODE_ID> <PRIV_IP> <QUORUM>
#   Once, on b1:   bash cluster_brokers.sh form <B1> <B2> <B3>
# QUORUM is "1@b1:29093,2@b2:29093,3@b3:29093".
set -euo pipefail
case "${1:?node|form}" in
node)
  ID="${2:?}"; PRIV="${3:?}"; Q="${4:?}"
  docker rm -f rediscl kafkacl >/dev/null 2>&1 || true
  # --cluster-announce-ip is required: without it nodes advertise container-internal
  # addresses and a genuinely distributed cluster cannot form.
  docker run -d --name rediscl --network host redis:7 \
    redis-server --port 7000 --cluster-enabled yes --cluster-config-file nodes.conf \
    --cluster-node-timeout 5000 --appendonly no --save '' --bind 0.0.0.0 \
    --cluster-announce-ip "$PRIV" >/dev/null
  docker run -d --name kafkacl --network host \
    -e KAFKA_NODE_ID="$ID" -e KAFKA_PROCESS_ROLES=broker,controller \
    -e KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=PLAINTEXT:PLAINTEXT,CONTROLLER:PLAINTEXT \
    -e KAFKA_LISTENERS=PLAINTEXT://0.0.0.0:29092,CONTROLLER://0.0.0.0:29093 \
    -e KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://"$PRIV":29092 \
    -e KAFKA_CONTROLLER_QUORUM_VOTERS="$Q" \
    -e KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER \
    -e KAFKA_INTER_BROKER_LISTENER_NAME=PLAINTEXT \
    -e KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=3 \
    -e KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR=3 \
    -e KAFKA_TRANSACTION_STATE_LOG_MIN_ISR=2 \
    -e KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS=0 \
    -e KAFKA_LOG_DIRS=/tmp/kraft-cluster-logs -e CLUSTER_ID=NkU3OEVBNTcwNTJENDM2Qw \
    -e KAFKA_NUM_PARTITIONS=3 -e KAFKA_DEFAULT_REPLICATION_FACTOR=3 \
    -e KAFKA_AUTO_CREATE_TOPICS_ENABLE=true -e KAFKA_HEAP_OPTS="-Xms1G -Xmx1G" \
    `# Retention caps -- see the note in brokers.sh. KAFKA_LOG_DIRS is inside the container,` \
    `# so without these the writable layer grows until the root filesystem is full and the` \
    `# broker dies with exit 1. Replication factor 3 here means three copies of every segment,` \
    `# so this host fills three times faster than the single-node case that already did.` \
    -e KAFKA_LOG_RETENTION_MS=900000 \
    -e KAFKA_LOG_RETENTION_BYTES=2147483648 \
    -e KAFKA_LOG_SEGMENT_BYTES=268435456 \
    apache/kafka:4.1.1 >/dev/null
  echo "node $ID up on $PRIV" ;;
form)
  B1="${2:?}"; B2="${3:?}"; B3="${4:?}"
  sudo docker exec rediscl redis-cli --cluster create \
    "$B1":7000 "$B2":7000 "$B3":7000 --cluster-yes
  sudo docker exec kafkacl /opt/kafka/bin/kafka-broker-api-versions.sh \
    --bootstrap-server "$B1":29092 | grep -c 'id:' ;;
esac
