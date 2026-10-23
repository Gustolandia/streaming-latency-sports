#!/usr/bin/env bash
# Start single-node Kafka + Redis on a broker host. Run as: sudo bash brokers.sh <PRIVATE_IP>
# Mirrors docker-compose.yml so cloud and local runs use identical broker configuration.
#
# Plan version 47 (23 Oct 2026): and, beside them, NATS with JetStream (block N) and RabbitMQ
# (block P). Every session starts each of them afresh, as it starts Kafka and Redis:
#     sudo bash cloud/brokers.sh <PRIVATE_IP> [kafka] [redis] [nats] [rabbitmq]
# With no broker named, all four run. Naming some runs those and stops the others, so that a
# session can put back exactly the brokers an earlier block ran beside (block U ran Kafka and
# Redis alone). What each broker is runs from the pins just below, which are the one place each is
# named, and what ran is printed at the end: each image's digest and the NATS server's version.
#
#   NATS      nats-server, a single Go binary that Ubuntu does not package, fetched from its GitHub
#             release and checked twice before it is installed: against the release's own
#             SHA256SUMS, and against the hash pinned here, so that a release file replaced later
#             fails as well. It is installed at a path of its version's own, beside the tools
#             block's /usr/local/bin/nats-server, and run as the unit sbl-nats-js, with JetStream on
#             and a store of its own, emptied each session. The tools block's own unit, sbl-nats,
#             runs with JetStream off on the same port, 4222, so it is stopped first and kept from
#             starting at boot; `bash cloud/azure/tools.sh brokers` puts it back.
#   RabbitMQ  the official image, on 5672, with its default user let in from the driver, as the
#             tools block lets its own in. Ubuntu's rabbitmq-server, which the tools block enables
#             on the same port, is stopped first and kept from starting at boot.
#
# Each broker is asked whether it answers before this ends, and one that does not stops it.
set -euo pipefail
PRIV="${1:?private IP required}"
shift

#: The images and the binary each broker runs from, each named here and nowhere else. Redis and
#: RabbitMQ are pinned by digest as well as tag, so that a tag moved later runs nothing new; Kafka
#: by its tag, its digest recorded in every run (scripts/run_facts.py broker). NATS's release is
#: checked against the two hashes below, which were checked against the release's SHA256SUMS and
#: GitHub's own digests of its assets.
KAFKA_IMAGE="apache/kafka:4.1.1"
REDIS_IMAGE="redis:7.4.11@sha256:44960b3100c48159a66d28c18b0588c193492e25f7551d60e51dd464fc3eca5b"
RABBITMQ_IMAGE="rabbitmq:4.3.7@sha256:ddb072727ae2209a054515e806b0daa875cf611a7bb8592345c7ddceaa8ef63c"
NATS_VERSION="v2.15.1"
NATS_SHA256_AMD64="bf5edc7b1ce98e885c368cb43a886eb148dc5d0551d99f3cf6141fb5e1954c70"
NATS_SHA256_ARM64="e2fbab4cad7d3c76e3052eb959570393c9d73ba756b70bf8e9eea61e9ae6d49c"
#: Where the pinned NATS server is installed and keeps its JetStream store.
NATS_DIR="/opt/sbl/nats-server-$NATS_VERSION"
NATS_STORE="/var/lib/sbl-nats-js"
#: RabbitMQ's own configuration file for the container, mounted where the image reads its extras.
RABBITMQ_CONF="/etc/sbl-rabbitmq/20-sbl.conf"

ALL="kafka redis nats rabbitmq"
WANTED="${*:-$ALL}"
for broker in $WANTED; do
  case " $ALL " in
    *" $broker "*) ;;
    *) echo "FATAL: the brokers are $ALL, not '$broker'" >&2; exit 2 ;;
  esac
done
wanted () { case " $WANTED " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }
fatal () { echo "FATAL: $*" >&2; exit 1; }
port_free () { ! ss -Hltn "sport = :$1" | grep -q .; }

docker rm -f broker redis rabbitmq >/dev/null 2>&1 || true
if wanted redis; then
  docker run -d --name redis -p 6379:6379 "$REDIS_IMAGE" \
    redis-server --save '' --appendonly no >/dev/null
fi
if wanted kafka; then
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
    "$KAFKA_IMAGE" >/dev/null
fi

# --- NATS with JetStream (block N) --------------------------------------------------------------
#: The pinned release, fetched and checked twice where it is not already installed; the archive
#: it came from is kept beside it, and checked against the pin again every session.
nats_install () {
  local arch=amd64 sum="$NATS_SHA256_AMD64"
  [ "$(uname -m)" = aarch64 ] && { arch=arm64; sum="$NATS_SHA256_ARM64"; }
  local asset="nats-server-$NATS_VERSION-linux-$arch.tar.gz"
  if [ -x "$NATS_DIR/nats-server" ] && [ -f "$NATS_DIR/$asset" ]; then
    (cd "$NATS_DIR" && echo "$sum  $asset" | sha256sum -c - >/dev/null) \
      || fatal "$NATS_DIR/$asset no longer matches the pinned hash"
    return 0
  fi
  local base="https://github.com/nats-io/nats-server/releases/download/$NATS_VERSION" work
  work=$(mktemp -d)
  curl -fsSL -o "$work/$asset" "$base/$asset" && curl -fsSL -o "$work/SHA256SUMS" "$base/SHA256SUMS" \
    || fatal "nats-server $NATS_VERSION could not be fetched from $base"
  (cd "$work" && grep "  $asset\$" SHA256SUMS | sha256sum -c - >/dev/null) \
    || fatal "$asset does not match the release's own SHA256SUMS"
  (cd "$work" && echo "$sum  $asset" | sha256sum -c - >/dev/null) \
    || fatal "$asset does not match the hash pinned in cloud/brokers.sh"
  tar -xzf "$work/$asset" -C "$work"
  [ -x "$work/nats-server-$NATS_VERSION-linux-$arch/nats-server" ] \
    || fatal "$asset holds no nats-server-$NATS_VERSION-linux-$arch/nats-server: $(tar -tzf "$work/$asset" | head -n 5 | tr '\n' ' ')"
  install -D -m 0755 "$work/nats-server-$NATS_VERSION-linux-$arch/nats-server" "$NATS_DIR/nats-server"
  cp "$work/$asset" "$NATS_DIR/$asset"
  rm -rf "$work"
}
#: The server's first line to a client, its INFO, which says whether JetStream is on.
nats_info () {
  timeout 5 bash -c 'exec 3<>/dev/tcp/127.0.0.1/4222 && head -n 1 <&3' 2>/dev/null
}
systemctl stop sbl-nats-js >/dev/null 2>&1 || true
if wanted nats; then
  nats_install
  systemctl disable --now sbl-nats >/dev/null 2>&1 || true
  port_free 4222 || fatal "port 4222 is held by something other than the tools block's NATS: $(ss -Hltnp 'sport = :4222')"
  rm -rf "$NATS_STORE"
  mkdir -p "$NATS_STORE"
  printf '[Unit]\nDescription=NATS with JetStream for plan version 47 (block N)\nAfter=network.target\n\n[Service]\nExecStart=%s -p 4222 -js -sd %s\n\n[Install]\nWantedBy=multi-user.target\n' \
    "$NATS_DIR/nats-server" "$NATS_STORE" > /etc/systemd/system/sbl-nats-js.service
  systemctl daemon-reload
  systemctl start sbl-nats-js
  said=""
  for _ in $(seq 1 15); do
    said=$(nats_info) && [ -n "$said" ] && break
    sleep 1
  done
  case "$said" in
    *'"jetstream":true'*) ;;
    *) fatal "nats-server did not answer on 4222 with JetStream on: ${said:-no answer}" ;;
  esac
fi

# --- RabbitMQ (block P) -------------------------------------------------------------------------
if wanted rabbitmq; then
  systemctl disable --now rabbitmq-server >/dev/null 2>&1 || true
  port_free 5672 || fatal "port 5672 is held by something other than Ubuntu's RabbitMQ: $(ss -Hltnp 'sport = :5672')"
  mkdir -p "$(dirname "$RABBITMQ_CONF")"
  printf 'loopback_users = none\n' > "$RABBITMQ_CONF"
  docker run -d --name rabbitmq -p 5672:5672 \
    -v "$RABBITMQ_CONF:/etc/rabbitmq/conf.d/20-sbl.conf:ro" "$RABBITMQ_IMAGE" >/dev/null
  # Docker's proxy takes a connection on 5672 before RabbitMQ listens behind it, so the broker
  # itself is asked, for up to two minutes: it boots in some tens of seconds. The tool asks as
  # the broker's own user: run as root before the broker is up, it writes the Erlang cookie
  # itself, as root, and the broker, which runs as rabbitmq, then cannot read it and stops
  # ("Error when reading /var/lib/rabbitmq/.erlang.cookie: eacces", 23 Oct 2026).
  up=""
  for _ in $(seq 1 60); do
    docker exec --user rabbitmq rabbitmq rabbitmq-diagnostics -q check_port_listener 5672 \
        >/dev/null 2>&1 \
      && { up=1; break; }
    sleep 2
  done
  [ -n "$up" ] || fatal "RabbitMQ did not listen on 5672 inside its container"
fi

sleep 20; docker ps --format '{{.Names}} {{.Status}}'
docker ps --format '{{.Names}}' | while read -r name; do
  docker inspect --format "$name {{.Config.Image}} {{.Image}}" "$name"
done
if wanted nats; then
  echo "sbl-nats-js $("$NATS_DIR/nats-server" --version) $(systemctl is-active sbl-nats-js)"
fi
