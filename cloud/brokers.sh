#!/usr/bin/env bash
# Start single-node Kafka + Redis on a broker host. Run as: sudo bash brokers.sh <PRIVATE_IP>
# Mirrors docker-compose.yml so cloud and local runs use identical broker configuration.
set -euo pipefail
PRIV="${1:?private IP required}"
docker rm -f broker redis >/dev/null 2>&1 || true
docker run -d --name redis -p 6379:6379 redis:7 \
  redis-server --save '' --appendonly no >/dev/null
docker run -d --name broker -p 19092:19092 \
  -e KAFKA_BROKER_ID=1 \
  -e KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=PLAINTEXT:PLAINTEXT,CONTROLLER:PLAINTEXT \
  -e KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://"$PRIV":19092 \
  -e KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1 \
  -e KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS=0 \
  -e KAFKA_TRANSACTION_STATE_LOG_MIN_ISR=1 \
  -e KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR=1 \
  -e KAFKA_PROCESS_ROLES=broker,controller -e KAFKA_NODE_ID=1 \
  -e KAFKA_CONTROLLER_QUORUM_VOTERS=1@localhost:29093 \
  -e KAFKA_LISTENERS=PLAINTEXT://0.0.0.0:19092,CONTROLLER://localhost:29093 \
  -e KAFKA_INTER_BROKER_LISTENER_NAME=PLAINTEXT \
  -e KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER \
  -e KAFKA_LOG_DIRS=/tmp/kraft-combined-logs \
  -e CLUSTER_ID=MkU3OEVBNTcwNTJENDM2Qk \
  -e KAFKA_NUM_PARTITIONS=1 -e KAFKA_DEFAULT_REPLICATION_FACTOR=1 \
  -e KAFKA_AUTO_CREATE_TOPICS_ENABLE=true \
  -e KAFKA_HEAP_OPTS="-Xms1G -Xmx1G" \
  `# Retention caps. KAFKA_LOG_DIRS above points INSIDE the container, so segments accumulate` \
  `# in the writable layer with no volume and nothing reclaiming them. On 2026-07-27 a campaign` \
  `# of ~100 three-minute cells filled a 45 GB root filesystem, the broker died with exit 1, and` \
  `# every subsequent cell failed to connect. Without these, the disk is a silent countdown whose` \
  `# length depends only on how many runs you do. 15 minutes and 2 GB are far more than any` \
  `# single cell needs and cannot accumulate.` \
  -e KAFKA_LOG_RETENTION_MS=900000 \
  -e KAFKA_LOG_RETENTION_BYTES=2147483648 \
  -e KAFKA_LOG_SEGMENT_BYTES=268435456 \
  apache/kafka:4.1.1 >/dev/null
sleep 20; docker ps --format '{{.Names}} {{.Status}}'
