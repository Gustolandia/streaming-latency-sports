#!/usr/bin/env bash
# The tools block: install the tools at the versions the audit read, and run T1 to T4.
#
# Each runnable tool is one campaign on one machine pair, with our own program recording the same
# messages, so every number a tool reports has a reference measured beside it. The versions are
# pinned before any run because a tool's behaviour is what T1 to T4 report, and a tool that
# changed under us would be a different experiment (the plan's Section "The tools").
#
#     bash cloud/azure/tools.sh brokers          # ON THE BROKER: the servers the tools speak to
#     bash cloud/azure/tools.sh install          # ON THE DRIVER: pinned versions, fingerprinted
#     bash cloud/azure/tools.sh t1 vegeta        # the delay staircase
#     bash cloud/azure/tools.sh t2 wrk2          # forced negatives, by moving the clock it reads
#     bash cloud/azure/tools.sh t3 vegeta        # idle against 88% load, with and without go-first
#     bash cloud/azure/tools.sh t4 vegeta        # what it can report at all
#
# Which machine runs which is not a detail. The servers go on the broker and the tools on the
# driver, so a tool's messages cross the same wire our own program's do and T1's delay, added on
# the broker's card, is on the path the tool actually uses. Every target defaulted to 127.0.0.1
# until 22 September, which put tool and server on one machine and left T1 unable to work at all.
#
# T2 moves the clock the tool reads with libfaketime, and refuses the Go tools: Go reads the
# clock without going through the C library, so the preload never reaches it and a run that
# looked fine would be a run with no offset at all. Those tools need the second machine whose
# clock is offset and then restored, which is not this script.
#
# Like stage 0 and every campaign, this carries on past a failing command on purpose: a check
# that fails becomes a STOP_RULE with a reason a person can read, not a silent exit.
. "$(dirname "${BASH_SOURCE[0]}")/../campaigns/common.sh"
set +e
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)" || exit 1

DIR="runs/azure/tools"
WORK="${WORK:-$HOME/tools}"
mkdir -p "$DIR" "$WORK"

log () { echo "$(date -u +%FT%TZ) $*"; }
stop () { log "STOP_RULE: $*"; exit 1; }

#: tool|how it is fetched|the version the audit read
#
# "resolve" means the pin is not written here yet. install records exactly what it fetched in
# installed.json and says so loudly; that resolved commit is written back into this table and
# committed before any T1 run, because a tool's behaviour is what the block reports and a tool
# that changed under us would be a different experiment. A made-up commit here would be worse
# than an honest blank.
#: Rewritten on 22 September, because until then five of the six hashes below were not commits.
#:
#: They were asked of their own repositories that day -- the first time any of them had been,
#: because the install step below had never fetched anything; it reported what was already on
#: the machine and stopped. Five came back 422, GitHub for "no commit with that SHA", and
#: GitHub's commit search found each of them in zero repositories anywhere. Only k6's was real,
#: and valkey's 9.1.2 is a real release tag.
#:
#: The real ones were in the repository the whole time, in data/tools_audit/batch_*.json, the
#: T5 audit's own records: a dated "version seen" for every one of the ten, and every hash in
#: them answers 200. **The audit did its work properly.** What was wrong was the copy into this
#: table, and the shape of the damage says as much -- each wrong hash shares its first 28 to 34
#: characters with the audit's and differs only in the tail:
#:
#:     vegeta   audit cf5811269046c672a604b1eb352204d30f16ae4a
#:              table cf5811269046c672a604b1eb352204d30f9d5b58    same through "...204d30f"
#:     hey      audit 5626f79b8698df6daf9b25799c9805c6acc96740
#:              table 5626f79b8698df6daf9b25799c9805c6ac7dbd9e    same through "...9805c6ac"
#:
#: and so for memtier, librdkafka and Kafka: transcriptions whose tails were regenerated rather
#: than copied. Three more -- wrk2, rabbitmq-perftest and nats-latency -- sat here as "resolve"
#: although the audit had a real commit for each. Nothing could contradict any of it, because
#: nothing read this table: it was written in e6870e38 on 20 September, the commit that created
#: this file, and the step that would have fetched these commits fetched nothing.
#:
#: The table is now the audit's, which is what this plan means by "the versions the audit read",
#: and not whatever happened to be HEAD on the day it was installed.
PINNED='
vegeta|go|cf5811269046c672a604b1eb352204d30f16ae4a
hey|go|5626f79b8698df6daf9b25799c9805c6acc96740
k6|go|3fcf5388d78c
valkey-benchmark|apt|9.1.2
memtier_benchmark|git|5694a3d61aaf0322a62fc44083ba6f2130b16265
rdkafka_performance|git|6f86c853a131d66fc2cd2a44aac99e83de859b4e
kafka-end-to-end|kafka|995cfcf99f7917403e030428c00b5c51808ddc61
kafka-producer-perf|kafka|995cfcf99f7917403e030428c00b5c51808ddc61
wrk2|git|44a94c17d8e6a0bac8559b53da76848e430cb7a7
rabbitmq-perftest|jar|ba718d2eae542ee5557a676f5454d4492739e714
nats-latency|go|cc0a8e3224d564b134a92f6f2c2081452f885549
'

#: The tools libfaketime can reach, because they read the clock through the C library.
FAKEABLE="wrk2 valkey-benchmark memtier_benchmark rdkafka_performance kafka-end-to-end \
kafka-producer-perf rabbitmq-perftest"
#: The tools it cannot: Go does not go through the C library for the clock.
GO_TOOLS="vegeta hey k6 nats-latency"

#: The Go toolchain the three Go tools are built with. Ubuntu 22.04 ships Go 1.18 and k6 needs
#: newer, so it is fetched rather than apt-installed -- and pinned, because the compiler is part
#: of what produced the binary whose behaviour this block reports.
GO_VERSION="1.22.5"

#: Each tool in its own function, each carrying on past its own failure. Nine of these ten can be
#: had without the tenth, and a block that reports on nine tools is worth more than one that
#: reports on none because a single upstream moved. What installed is fingerprinted below;
#: what did not is named.
have () { command -v "$1" >/dev/null 2>&1; }

get_go () {
  have go && return 0
  [ -x /usr/local/go/bin/go ] && { export PATH="/usr/local/go/bin:$PATH"; return 0; }
  local arch=amd64
  [ "$(uname -m)" = aarch64 ] && arch=arm64
  log "   fetching Go $GO_VERSION"
  (cd "$WORK" \
    && curl -fsSL -o go.tgz "https://go.dev/dl/go$GO_VERSION.linux-$arch.tar.gz" \
    && sudo rm -rf /usr/local/go && sudo tar -C /usr/local -xzf go.tgz) \
    || { log "   WARN: Go $GO_VERSION could not be fetched"; return 1; }
  export PATH="/usr/local/go/bin:$PATH"
}

go_tool () {
  local binary="$1" module="$2" version="$3"
  have "$binary" && { log "   $binary already here"; return 0; }
  get_go || return 1
  log "   building $binary from $module@$version"
  GOBIN="$WORK/bin" GOFLAGS=-mod=mod GOPATH="$WORK/go" GOCACHE="$WORK/gocache" \
    go install "$module@$version" >"$DIR/build_$binary.log" 2>&1 \
    || { log "   WARN: $binary did not build; see $DIR/build_$binary.log"; return 1; }
  # What "latest" actually resolved to, asked of the module proxy rather than assumed. A version
  # nobody fetched is how this table came to hold five hashes that were not commits.
  GOPATH="$WORK/go" GOCACHE="$WORK/gocache" GOFLAGS=-mod=mod \
    go list -m -f '{{.Path}}@{{.Version}}' "$module@$version" \
    > "$DIR/version_$binary.txt" 2>/dev/null
  sudo install -m 0755 "$WORK/bin/$binary" /usr/local/bin/ \
    || log "   WARN: $binary built but could not be installed"
}

git_build () {
  local name="$1" repo="$2" version="$3" binary="$4" ; shift 4
  have "$(basename "$binary")" && { log "   $name already here"; return 0; }
  local src="$WORK/$name"
  [ -d "$src" ] || git clone -q "$repo" "$src" \
    || { log "   WARN: $name could not be cloned"; return 1; }
  ( cd "$src" && git fetch -q --all 2>/dev/null
    [ "$version" = resolve ] || git checkout -q "$version" 2>/dev/null
    "$@" ) >"$DIR/build_$name.log" 2>&1 \
    || { log "   WARN: $name did not build; see $DIR/build_$name.log"; return 1; }
  sudo install -m 0755 "$src/$binary" /usr/local/bin/ \
    || log "   WARN: $name built but could not be installed"
  ( cd "$src" && git rev-parse HEAD ) > "$DIR/commit_$name.txt" 2>/dev/null
}

get_kafka () {
  have kafka-run-class.sh && { log "   kafka tools already here"; return 0; }
  local version="${KAFKA_VERSION:-3.7.1}" scala=2.13
  log "   fetching Kafka $version for its own tools"
  (cd "$WORK" \
    && curl -fsSL -o kafka.tgz \
         "https://archive.apache.org/dist/kafka/$version/kafka_$scala-$version.tgz" \
    && tar -xzf kafka.tgz) \
    || { log "   WARN: Kafka $version could not be fetched"; return 1; }
  echo "$version" > "$DIR/kafka_tools_version.txt"
  local home="$WORK/kafka_$scala-$version"
  local name
  for name in kafka-run-class.sh kafka-producer-perf-test.sh; do
    printf '#!/bin/sh\nexec %s/bin/%s "$@"\n' "$home" "$name" > "$WORK/$name"
    sudo install -m 0755 "$WORK/$name" /usr/local/bin/ \
      || log "   WARN: $name could not be installed"
  done
}

#: Built from its own source at the commit the audit read, not taken from a release.
#:
#: The tempting shortcut is the release jar: it is one download and it works. It is also the
#: wrong artefact. The audit read commit ba718d2e of 18 September 2026 and noted that the latest
#: release, 2.25.0, is from 30 June -- so the release is nearly three months *older* than the
#: source the audit looked at, and running the block against it would report on a build nobody
#: audited. This block exists to say what a tool does; which build of it is the whole question.
get_perftest () {
  local jar="$HOME/tools/perf-test.jar" version="$1"
  [ -s "$jar" ] && { log "   rabbitmq-perftest already here"; return 0; }
  command -v mvn >/dev/null || sudo apt-get install -y -qq maven \
    || { log "   WARN: maven is not available, so perf-test cannot be built"; return 1; }
  local src="$WORK/perftest"
  [ -d "$src" ] || git clone -q https://github.com/rabbitmq/rabbitmq-perf-test "$src" \
    || { log "   WARN: rabbitmq-perf-test could not be cloned"; return 1; }
  log "   building rabbitmq-perftest from $version"
  ( cd "$src" && git fetch -q --all 2>/dev/null && git checkout -q "$version" \
    && mvn -q -DskipTests -Dmaven.javadoc.skip=true package ) \
    > "$DIR/build_perftest.log" 2>&1 \
    || { log "   WARN: perf-test did not build; see $DIR/build_perftest.log"; return 1; }
  mkdir -p "$HOME/tools"
  local built
  built=$(ls -1 "$src"/target/perf-test*.jar 2>/dev/null | grep -v sources | head -1)
  [ -n "$built" ] || { log "   WARN: perf-test built no jar under target/"; return 1; }
  cp "$built" "$jar" || { log "   WARN: the perf-test jar could not be copied"; return 1; }
  ( cd "$src" && git rev-parse HEAD ) > "$DIR/commit_perftest.txt" 2>/dev/null
}

install () {
  log "== the tools, at the versions the audit read"
  sudo apt-get update -qq || stop "apt-get update failed"
  # Everything the builds below need. openjdk is for Kafka's own tools and RabbitMQ's PerfTest,
  # both of which are Java programs; libsasl2 and cmake are librdkafka's.
  sudo apt-get install -y -qq build-essential git pkg-config libssl-dev unzip cmake \
      libevent-dev autoconf automake libtool libpcre3-dev zlib1g-dev libsasl2-dev \
      openjdk-11-jdk-headless \
    || log "WARN: some packages were not available; each tool is checked below"

  echo "$PINNED" | while IFS='|' read -r tool how version; do
    [ -n "$tool" ] || continue
    if [ "$version" = resolve ]; then
      log "   $tool: $how, NOT YET PINNED -- what is installed is recorded below"
    else
      log "   $tool: $how, pinned at $version"
    fi
  done

  go_tool vegeta github.com/tsenart/vegeta/v12 cf5811269046c672a604b1eb352204d30f16ae4a
  go_tool hey github.com/rakyll/hey 5626f79b8698df6daf9b25799c9805c6acc96740
  go_tool k6 go.k6.io/k6/v2 3fcf5388d78c
  go_tool nats github.com/nats-io/natscli/nats cc0a8e3224d564b134a92f6f2c2081452f885549
  git_build wrk2 https://github.com/giltene/wrk2 44a94c17d8e6a0bac8559b53da76848e430cb7a7 wrk make -j2
  git_build memtier https://github.com/RedisLabs/memtier_benchmark \
    5694a3d61aaf0322a62fc44083ba6f2130b16265 memtier_benchmark \
    sh -c 'autoreconf -ivf && ./configure && make -j2'
  git_build librdkafka https://github.com/confluentinc/librdkafka \
    6f86c853a131d66fc2cd2a44aac99e83de859b4e examples/rdkafka_performance \
    sh -c './configure && make -j2 && make -C examples rdkafka_performance'
  git_build valkey https://github.com/valkey-io/valkey 9.1.2 src/valkey-benchmark make -j2
  get_kafka
  get_perftest ba718d2eae542ee5557a676f5454d4492739e714

  # What is actually on this machine afterwards, with its own fingerprint, so a run can say which
  # build produced its numbers rather than which version we meant to install.
  python3 - "$DIR/installed.json" <<'PY'
import hashlib, json, os, shutil, subprocess, sys
found = {}
for tool, binary in (("vegeta", "vegeta"), ("hey", "hey"), ("k6", "k6"), ("wrk2", "wrk"),
                     ("valkey-benchmark", "valkey-benchmark"),
                     ("memtier_benchmark", "memtier_benchmark"),
                     ("rdkafka_performance", "rdkafka_performance"),
                     ("nats-latency", "nats"),
                     ("kafka-end-to-end", "kafka-run-class.sh"),
                     ("kafka-producer-perf", "kafka-producer-perf-test.sh")):
    where = shutil.which(binary)
    if not where:
        found[tool] = {"present": False}
        continue
    with open(where, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    try:
        said = subprocess.run([where, "--version"], capture_output=True, text=True,
                              timeout=20).stdout.strip()[:200]
    except Exception:
        said = ""
    found[tool] = {"present": True, "path": where, "sha256": digest, "version_says": said}
# RabbitMQ's PerfTest is a jar rather than a program on the path, so it is fingerprinted where
# it sits.
jar = os.path.expanduser(os.environ.get("SBL_PERFTEST_JAR", "~/tools/perf-test.jar"))
if os.path.exists(jar):
    with open(jar, "rb") as fh:
        found["rabbitmq-perftest"] = {"present": True, "path": jar,
                                      "sha256": hashlib.sha256(fh.read()).hexdigest(),
                                      "version_says": ""}
else:
    found["rabbitmq-perftest"] = {"present": False}
with open(sys.argv[1], "w", encoding="utf-8") as fh:
    json.dump(found, fh, indent=2, sort_keys=True)
print("\n".join("   %-22s %s" % (t, "ok" if v["present"] else "MISSING")
                for t, v in sorted(found.items())))
PY
  log "CAMPAIGN_COMPLETE: what is installed is in $DIR/installed.json"
  if echo "$PINNED" | grep -q '|resolve$'; then
    log "STOP_RULE: some tools are not pinned yet. Write the fingerprints installed.json records"
    log "           into the PINNED table and commit them before any T1, T2, T3 or T4 run."
  fi
}

# The servers the ten tools speak to. Run on the broker host, not on the driver.
#
# Installed natively rather than in containers on purpose: a container puts a network namespace
# and a set of firewall rules between the tool and the broker, which adds its own delay and its
# own scheduling. This block measures tenths of a millisecond, so an extra hop would land inside
# the thing being measured. Kafka and Valkey are already standing from the law campaigns; these
# are the two that only the tools block needs, plus the web server the HTTP tools talk to.
brokers () {
  log "== the servers the tools block needs, on this host"
  sudo apt-get update -qq || stop "apt-get update failed"
  sudo apt-get install -y -qq nginx rabbitmq-server \
    || log "WARN: nginx or rabbitmq-server was not available; each is checked below"

  # nats-server is a single Go binary and is not in Ubuntu's archive. Its release assets carry
  # the version in their own names -- nats-server-v2.11.0-linux-amd64.zip -- so GitHub's
  # "latest/download/<name>" shortcut, which needs the name to be fixed, answers 404 for it. That
  # is what it did on 22 September, and because the check below is about what answers rather than
  # what installed, it stopped the whole tools block at its first job. The tag is resolved first
  # and written down, because which server answered is part of what this block reports.
  if ! command -v nats-server >/dev/null; then
    local arch=amd64
    [ "$(uname -m)" = aarch64 ] && arch=arm64
    # The release is asked for its own asset rather than having one guessed from the tag: the
    # guess was a .zip and what they publish is a .tar.gz, so a correctly resolved version still
    # 404'd. What the release says it has is the only thing that cannot be out of date.
    local asset
    asset=$(curl -fsSL https://api.github.com/repos/nats-io/nats-server/releases/latest \
            | sed -n 's/.*"browser_download_url": *"\([^"]*linux-'"$arch"'\.tar\.gz\)".*/\1/p' \
            | head -1)
    if [ -z "$asset" ]; then
      log "WARN: the latest nats-server release named no linux-$arch archive; checked below"
    else
      echo "$asset" > "$DIR/nats_server_asset.txt"
      (cd "$WORK" && curl -fsSL -o nats.tar.gz "$asset" && tar -xzf nats.tar.gz \
        && sudo install -m 0755 nats-server-*-linux-"$arch"/nats-server \
             /usr/local/bin/nats-server) \
        || log "WARN: nats-server could not be installed from $asset; it is checked below"
    fi
  fi
  # A site of our own on 8080, serving one small fixed file. The tools' own numbers include
  # however long the server took, so what it serves has to be the same every time and the same
  # for every tool; Ubuntu's default page is neither a fixed size nor ours to rely on.
  sudo mkdir -p /var/www/sbl
  printf '%512s' x | sudo tee /var/www/sbl/index.html >/dev/null
  printf 'server {\n  listen 8080 default_server;\n  root /var/www/sbl;\n  access_log off;\n}\n' \
    | sudo tee /etc/nginx/sites-available/sbl >/dev/null
  sudo ln -sf /etc/nginx/sites-available/sbl /etc/nginx/sites-enabled/sbl
  sudo nginx -t >/dev/null 2>&1 || stop "the nginx site for the tools block does not parse"
  sudo systemctl enable --now nginx rabbitmq-server >/dev/null 2>&1
  sudo systemctl reload nginx >/dev/null 2>&1
  command -v nats-server >/dev/null && \
    (pgrep -x nats-server >/dev/null || (nohup nats-server -p 4222 >"$WORK/nats.log" 2>&1 &))

  # What is actually answering, which is the only thing a campaign can rely on -- but asked for
  # up to fifteen seconds rather than once. These servers are started a few lines above and a
  # cold one is not listening by the time the next statement runs: on 22 September nats-server
  # logged "Server is ready" at 10:56:10.503 and this check had already called it dead in the
  # same second, which stopped the whole tools block.
  local bad=0
  for pair in "nginx 8080 http" "rabbitmq-server 5672 amqp" "nats-server 4222 nats"; do
    set -- $pair
    local waited=0
    while ! (echo > "/dev/tcp/127.0.0.1/$2") 2>/dev/null && [ "$waited" -lt 15 ]; do
      sleep 1; waited=$(( waited + 1 ))
    done
    if (echo > "/dev/tcp/127.0.0.1/$2") 2>/dev/null; then
      log "   $1 answering on $2${waited:+ after ${waited}s}"
    else
      log "   $1 NOT answering on $2 after ${waited}s"; bad=1
    fi
  done
  [ "$bad" = 0 ] || stop "a server the tools block needs is not answering; see above"
  log "CAMPAIGN_COMPLETE: the tools block's servers are up"
}

# T1: the delay staircase, receiver-only, in random order, with our reference beside it.
#: The delay is added where the law campaigns add it: on the broker's own card, to the traffic
#: bound for the machine running the client. It is applied over SSH because this stage runs on
#: the driver, where the tool runs, and the delay belongs on the other end of the wire.
hold_for () {
  local ms="$1"
  ssh -n -i "$SSH_KEY" -o BatchMode=yes -o StrictHostKeyChecking=no "ubuntu@$BROKER_PRIV" \
    "cd sbl && sudo python3 scripts/receiver_delay.py broker --dst $RECEIVER_IP \
       --delay-ms $ms --apply"
}

#: Every tool runs inside the receiver's namespace, because that is where the delay can reach it.
#:
#: These machines have accelerated networking, so the driver's own address sends and receives
#: through a hardware function -- enP2839s1 on the Arm pair -- which never touches eth0's
#: queueing discipline. netem lives on eth0. On 22 September a 20 ms delay was installed on the
#: broker toward the driver's address, confirmed present with tc, and the round trip did not
#: move: 1.36 ms against 1.86 with no delay at all. The tool saw nothing either, and reported a
#: flat 0.32 ms across a staircase from 0.1 to 1.5 ms -- data that looks perfectly reasonable and
#: means nothing.
#:
#: The receiver's namespace is an ipvlan on eth0, so its traffic is handled in software and the
#: delay does reach it. That is why every law campaign measures there, and it is the path a tool
#: has to be on for its number to stand beside ours.
NETNS="sudo ip netns exec sblrecv"

needs_namespace () {
  ip netns list 2>/dev/null | grep -q "^sblrecv" \
    || stop "the receiver's namespace is missing, and a tool outside it is not reached by the delay: it would report a flat staircase. Run cloud/azure/session.sh for this pair first"
}

#: Asked before the staircase, because the fault above produces believable numbers. A delay that
#: is installed and not felt is the one thing this stage cannot notice by looking at its results.
delay_arrives () {
  local idle held
  release_delay
  idle=$($NETNS ping -c 5 -q "$BROKER_PRIV" 2>/dev/null | awk -F/ '/rtt|round-trip/ {print $5}')
  hold_for 20 >/dev/null 2>&1
  held=$($NETNS ping -c 5 -q "$BROKER_PRIV" 2>/dev/null | awk -F/ '/rtt|round-trip/ {print $5}')
  release_delay
  [ -n "$idle" ] && [ -n "$held" ] \
    || stop "the path to $BROKER_PRIV could not be timed from the receiver's namespace"
  python3 -c 'import sys
idle, held = float(sys.argv[1]), float(sys.argv[2])
print("   the path moves %.2f ms when 20 ms is added (idle %.2f, held %.2f)"
      % (held - idle, idle, held))
sys.exit(0 if held - idle > 10.0 else 1)' "$idle" "$held" \
    || stop "20 ms was added on the broker and the path did not move by half of it: the delay is not reaching this tool, so its staircase would be flat and mean nothing"
}

release_delay () {
  ssh -n -i "$SSH_KEY" -o BatchMode=yes -o StrictHostKeyChecking=no "ubuntu@$BROKER_PRIV" \
    "cd sbl && sudo python3 scripts/receiver_delay.py broker-clear --apply" >/dev/null 2>&1
}

#: Our own program's trips on the same path, measured at the zero step.
#:
#: This block's whole premise is in its first paragraph: every number a tool reports has a
#: reference measured beside it. Nothing took that reference. reference_trips.json was read in
#: two places and written in none, so T2 -- which sets its offsets from the median true trip and
#: cancels the tool's own bias against it -- would have stopped on its first run, hours after
#: the tools were built, saying it needed a file nothing creates.
#:
#: The reference is our own client, the same one every law campaign uses, against the same
#: broker. That is possible for the tools that speak Kafka or Redis, which is all five of the
#: ones T2 can reach on the x86 pair. wrk2 speaks HTTP and RabbitMQ's PerfTest speaks AMQP, and
#: we have no client of our own for either, so T2 for those two says so rather than guessing.
#: Called the way campaign.sh calls it, and for the same reason: "the same client every law
#: campaign uses" has to mean the same client, the same workload and the same path, or the trip
#: it measures is not the trip the tools are being read against. Its first version passed only a
#: run id and a plan, which left the trial on all of its own defaults -- localhost for the
#: broker, so the consumer was refused at 127.0.0.1:6379 while redis ran on the other machine;
#: a StatsBomb plan at whatever rate it happens to hold, where every campaign runs a synthetic
#: constant-rate one; and no consumer wrap, so nothing sat behind the receiver's address. The
#: staircase either side of it was sound, and T2 refused to start for want of the file this
#: writes -- which is the refusal working.
reference_for () {
  local tool="$1" out="$2" backend id plan speedup me
  case "$tool" in
    valkey-benchmark|memtier_benchmark) backend=redis ;;
    rdkafka_performance|kafka-end-to-end|kafka-producer-perf) backend=kafka ;;
    *) log "   no client of ours speaks $tool's protocol, so no reference is taken"; return 1 ;;
  esac
  id="toolsref-$tool-$(date -u +%Y%m%dT%H%M%SZ)"
  plan="data/synthetic/constant_r${RATE:-50}_d${DURATION:-130}/replay_plan.csv"
  [ -s "$plan" ] \
    || { log "   WARN: no synthetic plan at $plan, so no reference is taken"; return 1; }
  speedup=$(assert_plan_rate "$plan" 1) \
    || { log "   WARN: no speedup for $plan, so no reference is taken"; return 1; }
  me=$(id -un)
  log "   our own $backend client on the same path, for the reference"
  if [ "$backend" = kafka ]; then
    SBL_CONSUMER_WRAP="$NETNS sudo -u $me" \
      timeout -k 30 900 bash scripts/run_kafka_trial.sh "$id" "$plan" \
        "$speedup" "${DURATION:-130}" -BOOTSTRAP "$KAFKA_BOOTSTRAP" \
        -PRODUCER_EXTRA "$KAFKA_PRODUCER_EXTRA" -IDLE_SECONDS 15 \
        > "$out/reference.log" 2>&1
  else
    SBL_CONSUMER_WRAP="$NETNS sudo -u $me" \
      timeout -k 30 900 bash scripts/run_redis_trial.sh "$id" "$plan" \
        "$speedup" "${DURATION:-130}" -RedisHost "$REDIS_HOST" -PORT "$REDIS_PORT" \
        -CONSUMER_EXTRA "$REDIS_CONSUMER_EXTRA" -IDLE_SECONDS 15 \
        > "$out/reference.log" 2>&1
  fi \
    || { log "   WARN: the reference run did not finish; see $out/reference.log"; return 1; }
  python3 -c 'import json, sys
sys.path.insert(0, "scripts")
import pilot_checks
trip, _gotit, _measured = pilot_checks.spans(sys.argv[1], 30.0)
if not trip:
    raise SystemExit("the reference run recorded no trips")
json.dump({"run_dir": sys.argv[1], "trips_ms": trip}, open(sys.argv[2], "w"))' \
    "runs/$id" "$out/reference_trips.json" \
    || { log "   WARN: the reference trips could not be read from runs/$id"; return 1; }
}

t1 () {
  local tool="${1:?which tool}"
  local steps="0 0.1 0.2 0.3 0.5 0.7 0.9 1.1 1.5 2.0"
  local order; order=$(echo $steps | tr ' ' '\n' | shuf | tr '\n' ' ')
  log "== T1 $tool: the delay staircase, in the order $order"
  needs_namespace
  delay_arrives
  for ms in $order; do
    local run="t1-$tool-$(echo "$ms" | tr . _)ms"
    mkdir -p "$DIR/$run"
    hold_for "$ms" > "$DIR/$run/delay.json" 2>&1 \
      || stop "the $ms ms delay could not be applied on $BROKER_PRIV"
    SBL_TOOL_WRAP="$NETNS" bash cloud/azure/tools_run.sh "$tool" "$DIR/$run" \
      > "$DIR/$run/tool.txt" 2>&1
    python3 scripts/tool_readings.py read --tool "$tool" --file "$DIR/$run/tool.txt" \
      --out "$DIR/$run/reading.json" >/dev/null 2>&1 \
      || log "WARN: $tool reported no latency at $ms ms; kept as a reading of nothing"
    #: At the zero step only, and after the tool has run so the two are not on the wire at once.
    #: T2 reads this file from t1-<tool>-0ms and will not start without it.
    [ "$ms" = 0 ] && reference_for "$tool" "$DIR/$run"
    log "   $ms ms done"
  done
  release_delay
  log "CAMPAIGN_COMPLETE: T1 $tool; its runs are under $DIR"
}

# The spelling of an offset that libfaketime actually honours, found by measuring it.
#
# Its documented offsets are whole days, hours, minutes and seconds, and the fractional and
# millisecond spellings differ between builds. Rather than assume one, each is tried and the
# achieved shift is measured against a clock that was not faked. Nothing is run at an offset
# this could not confirm, because a T2 run with no offset looks exactly like a tool that handles
# negatives perfectly, and that is the one mistake this block cannot afford.
faketime_spelling () {
  local ms="$1" spelling before after moved
  command -v faketime >/dev/null || return 1
  for spelling in "-${ms}ms" "-0$(python3 -c "print('%.9f' % (${ms}/1000.0))" | cut -c2-)" \
                  "-$(python3 -c "print('%.6f' % (${ms}/1000.0))")s"; do
    before=$(date +%s.%N)
    after=$(faketime -f "$spelling" date +%s.%N 2>/dev/null) || continue
    [ -n "$after" ] || continue
    # How far back it moved, in milliseconds, against a real reading taken just before.
    moved=$(python3 -c "import sys; print('%.4f' % ((float(sys.argv[1]) - float(sys.argv[2])) * 1000.0))" \
      "$before" "$after" 2>/dev/null) || continue
    if python3 -c "import sys; m=float(sys.argv[1]); w=float(sys.argv[2]); sys.exit(0 if 0.5*w <= m <= 2.0*w else 1)" \
        "$moved" "$ms" 2>/dev/null; then
      echo "$spelling"; return 0
    fi
  done
  return 1
}

# T2: forced negatives. Move the clock the tool reads back by 0.5 ms and 2 ms, change nothing
# else, and ask what it did with the values that came out below zero.
t2 () {
  local tool="${1:?which tool}"
  case " $GO_TOOLS " in
    *" $tool "*)
      stop "$tool is a Go program: it reads the clock without the C library, so libfaketime never reaches it. T2 for this tool needs the second machine with an offset clock, restored afterwards, which is not this script" ;;
  esac
  case " $FAKEABLE " in
    *" $tool "*) ;;
    *) stop "$tool is not in either T2 list; add it to FAKEABLE or GO_TOOLS having checked which clock it reads" ;;
  esac
  sudo apt-get install -y -qq faketime >/dev/null 2>&1

  # The offsets come from the trip they act on, not from a fixed pair of numbers (plan version
  # 15, D15-1). Half a millisecond against a 3 ms trip puts nothing below zero, and a tool
  # reading whole milliseconds needs the offset past its own step before it meets a negative at
  # all -- so the session's own median trip plus one and plus three is what T2 runs at.
  local trips="$DIR/t1-$tool-0ms/reference_trips.json"
  [ -s "$trips" ] || stop "T2 needs T1's zero-delay run for $tool first: its trips set the offsets and its reading cancels this tool's own bias"
  local median offsets
  median=$(python3 -c 'import json,statistics,sys
loaded = json.load(open(sys.argv[1]))
print("%.3f" % statistics.median(loaded["trips_ms"] if isinstance(loaded, dict) else loaded))' \
    "$trips") || stop "the median trip could not be read from $trips"
  offsets=$(python3 -c 'import sys; t=float(sys.argv[1]); print("%.3f %.3f" % (t+1.0, t+3.0))' \
    "$median")
  log "== T2 $tool: forced negatives; median trip $median ms, offsets $offsets"

  # What T1 found this tool can report at all. T2 predicts each behaviour through that step,
  # because a tool that cannot report a tenth of a millisecond never sees one below zero either
  # (D15-2). Where T1 found none, T2 falls back to the step the tool prints in, which is a
  # bound on it rather than a measurement, and says so.
  local step plain="$DIR/t1-$tool-0ms/reading.json"
  python3 scripts/tool_readings.py staircase --tool "$tool" --dir "$DIR" \
    --out "$DIR/t1-$tool-step.json" >/dev/null 2>&1
  step=$(python3 -c 'import json,sys
found = json.load(open(sys.argv[1]))
print(found["smallest_reported_ms"] or "")' "$DIR/t1-$tool-step.json" 2>/dev/null)
  if [ -z "$step" ]; then
    step=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["step_ms"] or "")' \
      "$plain" 2>/dev/null)
    log "   T1 found no step this tool reports; using the $step ms it prints in, which is a bound"
  else
    log "   T1 measured its smallest reportable step at $step ms"
  fi

  for ms in $offsets; do
    local run="t2-$tool-$(echo "$ms" | tr . _)ms"
    mkdir -p "$DIR/$run"
    local spelling
    spelling=$(faketime_spelling "$ms") \
      || stop "no libfaketime offset of $ms ms could be confirmed on this machine; T2 will not run an offset it cannot show reached the clock"
    echo "$spelling" > "$DIR/$run/offset_spelling.txt"
    log "   $ms ms, as $spelling"
    SBL_TOOL_WRAP="faketime -f $spelling" bash cloud/azure/tools_run.sh "$tool" "$DIR/$run" \
      > "$DIR/$run/tool.txt" 2>&1
    echo "$?" > "$DIR/$run/exit_code.txt"
    python3 scripts/tool_readings.py read --tool "$tool" --file "$DIR/$run/tool.txt" \
      --out "$DIR/$run/reading.json" >/dev/null 2>&1 \
      || log "   it reported no latency at all under the offset; kept as that"
    # Our own trips for the same messages are the reference the verdict is measured against;
    # T1's zero-delay reading of the same tool is what cancels that tool's own bias out of the
    # comparison, and T1's measured step is what the prediction passes through.
    if [ -s "$DIR/$run/reference_trips.json" ]; then
      python3 scripts/tool_negatives.py judge --reading "$DIR/$run/reading.json" \
        --reference "$DIR/$run/reference_trips.json" --offset-ms "$ms" \
        --plain "$plain" ${step:+--step-ms "$step"} \
        --exit-code "$(cat "$DIR/$run/exit_code.txt")" --out "$DIR/$run/verdict.json" \
        || log "   UNDECIDED at $ms ms; see $DIR/$run/verdict.json"
    else
      log "   WARN: no reference trips beside this run, so nothing can be judged from it"
    fi
  done
  log "CAMPAIGN_COMPLETE: T2 $tool; its runs are under $DIR"
}

# T3: idle against 88% load, with and without go-first priority on the tool's own process.
t3 () {
  local tool="${1:?which tool}"
  log "== T3 $tool: idle and at 88% load, with and without go-first"
  needs_namespace
  for load in 0 88; do
    for first in no yes; do
      local run="t3-$tool-l$load-first$first"
      mkdir -p "$DIR/$run"
      local wrap="$NETNS"
      [ "$first" = yes ] && wrap="$NETNS chrt -f 80"
      if [ "$load" != 0 ]; then
        stress-ng --cpu "$(nproc)" --cpu-load "$load" --timeout 600s >/dev/null 2>&1 &
        local stress=$!
        sleep 5
      fi
      SBL_TOOL_WRAP="$wrap" bash cloud/azure/tools_run.sh "$tool" "$DIR/$run" \
        > "$DIR/$run/tool.txt" 2>&1
      python3 scripts/tool_readings.py read --tool "$tool" --file "$DIR/$run/tool.txt" \
        --out "$DIR/$run/reading.json" >/dev/null 2>&1 || true
      [ "$load" != 0 ] && { kill "$stress" 2>/dev/null; wait "$stress" 2>/dev/null; }
      log "   load $load%, go-first $first done"
    done
  done
  log "CAMPAIGN_COMPLETE: T3 $tool; its runs are under $DIR"
}

# T4: which trips the tool can report at all, confirmed from a real output file.
t4 () {
  local tool="${1:?which tool}"
  local run="t4-$tool"
  mkdir -p "$DIR/$run"
  log "== T4 $tool: what it can report at all"
  needs_namespace
  SBL_TOOL_WRAP="$NETNS" bash cloud/azure/tools_run.sh "$tool" "$DIR/$run" \
    > "$DIR/$run/tool.txt" 2>&1
  python3 scripts/tool_readings.py read --tool "$tool" --file "$DIR/$run/tool.txt" \
    --out "$DIR/$run/reading.json" >/dev/null 2>&1 \
    || stop "$tool printed no latency at all, so T4 has nothing to confirm from"
  python3 -c 'import json,sys
r = json.load(open(sys.argv[1]))
print("   reports: %s" % ", ".join(sorted(r["reported_ms"])))
print("   its own step: %s ms" % r["step_ms"])' "$DIR/$run/reading.json"
  log "CAMPAIGN_COMPLETE: T4 $tool; see $DIR/$run/reading.json"
}

#: The reference on its own, for a staircase that already ran without one.
#:
#: T1 takes it at the zero step and T2 will not start without it. When the reference was calling
#: the trial on its defaults it could not connect, and five staircases were measured soundly with
#: no reference beside them. Re-running T1 would overwrite those measurements with a second set
#: for the sake of one file, so this takes the file instead: the same 0 ms hold the zero step
#: applies, the same call, into the same folder, with a note saying it was taken afterwards and
#: the failed attempt's log kept beside it. It refuses where a reference already exists, because
#: the one T1 took is the one the design asks for.
reference () {
  local tool="${1:?which tool}"
  #: Its own statement. Bash expands every word of a `local` before it runs any of them, so a
  #: second name on the same line cannot use the first: under `set -u` this read "tool: unbound
  #: variable" and the job was over in the same second it started. The queue's own field reader
  #: was written twice for the same reason.
  local run="$DIR/t1-$tool-0ms"
  [ -d "$run" ] || stop "there is no zero-delay run for $tool under $DIR to put a reference in"
  [ -s "$run/reference_trips.json" ] \
    && stop "$tool already has the reference T1 took; this would replace it"
  log "== the reference for $tool, taken after its staircase"
  needs_namespace
  hold_for 0 > "$run/delay.reference.json" 2>&1 \
    || stop "the 0 ms delay could not be applied on $BROKER_PRIV"
  [ -s "$run/reference.log" ] && mv "$run/reference.log" "$run/reference.first_attempt.log"
  date -u +%FT%TZ > "$run/reference.taken_after_the_staircase"
  reference_for "$tool" "$run" || stop "the reference for $tool could not be taken"
  release_delay
  log "CAMPAIGN_COMPLETE: the reference for $tool is in $run/reference_trips.json"
}

case "${1:-}" in
  brokers) brokers ;;
  install) install ;;
  reference) reference "${2:-}" ;;
  t1) t1 "${2:-}" ;;
  t2) t2 "${2:-}" ;;
  t3) t3 "${2:-}" ;;
  t4) t4 "${2:-}" ;;
  *) echo "usage: bash cloud/azure/tools.sh brokers | install | reference <tool> |" >&2
     echo "       t1 <tool> | t2 <tool> | t3 <tool> | t4 <tool>" >&2
     exit 2 ;;
esac
