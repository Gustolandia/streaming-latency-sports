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
# T2 moves the clock the tool reads with libfaketime. The Go tools read the clock without going
# through the C library, so the preload never reaches them, and a run that looked fine would be a
# run with no offset at all: for those, T2 steps this machine's own clock, measured against the
# hypervisor's PTP clock, and puts it back after each run (step_clock, since 25 September).
#
# Like stage 0 and every campaign, this carries on past a failing command on purpose: a check
# that fails becomes a STOP_RULE with a reason a person can read, not a silent exit.
. "$(dirname "${BASH_SOURCE[0]}")/../campaigns/common.sh"
set +e
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)" || exit 1

#: D4-2: tool campaigns run four rounds. Round 1 is runs/azure/tools, where it has always been, and
#: each later round has a folder of its own, so no round writes over another's runs. Until 25
#: September there was no round here at all: the block ran once where the plan asks for four,
#: and a second pass would have landed on top of the first.
ROUND="${SBL_TOOLS_ROUND:-1}"
case "$ROUND" in
  1) DIR="runs/azure/tools" ;;
  [2-9]) DIR="runs/azure/tools_round$ROUND" ;;
  *) echo "SBL_TOOLS_ROUND is a round from 1 to 9, not '$ROUND'" >&2; exit 2 ;;
esac
#: The AMQP broker our own reference client talks to: the same default the tools are given in
#: tools_run.sh, so the reference and PerfTest are pointed at one broker by one rule.
RABBIT="${SBL_RABBIT:-amqp://guest:guest@${BROKER_PRIV:-}:5672}"
WORK="${WORK:-$HOME/tools}"
mkdir -p "$DIR" "$WORK"

log () { echo "$(date -u +%FT%TZ) $*"; }
stop () { log "STOP_RULE: $*"; exit 1; }

#: A stage writes into folders named for the tool and the step, and nothing stopped a second pass
#: writing over the first. A round that already holds any of a stage's runs will not run that
#: stage again; putting a stage right means moving its runs aside first, with the reason beside
#: them, as every set-aside run of 24 and 25 September was.
not_run_yet () {  # stage, tool, a pattern for the runs that stage writes
  local found
  found=$(compgen -G "$DIR/$3" | head -n 1)
  [ -z "$found" ] \
    || stop "$1 for $2 has already run in round $ROUND ($(dirname "$found")); this would write over it"
}

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
#: Whether a jar can be started at all. `java -jar` needs a Main-Class in the manifest, and
#: Maven's `package` leaves a plain perf-test-<version>.jar without one beside the runnable one.
#: The plain jar was the first the glob found, it was copied, fingerprinted and recorded as
#: installed because the file was there, and every run of it said "no main manifest attribute".
runnable_jar () {
  python3 - "$1" <<'PY'
import sys, zipfile
try:
    with zipfile.ZipFile(sys.argv[1]) as jar:
        text = jar.read("META-INF/MANIFEST.MF").decode("utf-8", "replace")
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if any(line.startswith("Main-Class:") for line in text.splitlines()) else 1)
PY
}

get_perftest () {
  local jar="$HOME/tools/perf-test.jar" version="$1"
  [ -s "$jar" ] && runnable_jar "$jar" && { log "   rabbitmq-perftest already here"; return 0; }
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
  local built candidate
  built=""
  for candidate in $(ls -1 "$src"/target/perf-test*.jar 2>/dev/null | grep -v sources); do
    runnable_jar "$candidate" && { built="$candidate"; break; }
  done
  #: Some versions put the runnable one behind a profile. Asked for only when the ordinary build
  #: left nothing that can be started, so the usual case costs no second build.
  if [ -z "$built" ]; then
    log "   no runnable jar from the ordinary build; asking for the uber one"
    ( cd "$src" && mvn -q -DskipTests -Dmaven.javadoc.skip=true -Puber-jar package ) \
      >> "$DIR/build_perftest.log" 2>&1
    for candidate in $(ls -1 "$src"/target/perf-test*.jar 2>/dev/null | grep -v sources); do
      runnable_jar "$candidate" && { built="$candidate"; break; }
    done
  fi
  [ -n "$built" ] \
    || { log "   WARN: perf-test built no jar with a Main-Class under target/"; return 1; }
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
  #: The client our own AMQP reference speaks through (scripts/amqp_reference.py). Pinned like
  #: the tools, and system-wide, because the reference runs as this user inside the receiver's
  #: namespace, where a user-local install is not on the path sudo gives it.
  sudo pip3 install -q "pika==1.3.2" >/dev/null 2>&1 \
    && log "   pika $(python3 -c 'import pika; print(pika.__version__)' 2>/dev/null), for the AMQP reference" \
    || log "   WARN: pika did not install, so rabbitmq-perftest can have no reference"

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


def startable(path):
    """`java -jar` needs a Main-Class. A jar without one is a file, not a tool: Maven leaves a
    plain perf-test jar beside the runnable one, and the plain one was recorded as installed
    because it existed. Every run of it printed "no main manifest attribute" instead."""
    import zipfile
    try:
        with zipfile.ZipFile(path) as opened:
            text = opened.read("META-INF/MANIFEST.MF").decode("utf-8", "replace")
    except Exception:
        return False
    return any(line.startswith("Main-Class:") for line in text.splitlines())


if os.path.exists(jar) and startable(jar):
    with open(jar, "rb") as fh:
        found["rabbitmq-perftest"] = {"present": True, "path": jar,
                                      "sha256": hashlib.sha256(fh.read()).hexdigest(),
                                      "version_says": ""}
else:
    found["rabbitmq-perftest"] = {"present": False,
                                  "why": ("no Main-Class in its manifest" if os.path.exists(jar)
                                          else "no jar at %s" % jar)}
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
#: The servers belong on the broker, and this script's header says so. On 24 September `brokers`
#: was run on the driver anyway, and nothing stopped it: it installed and configured the servers
#: there, asked 127.0.0.1 whether they answered, and they did -- the driver's own. The broker the
#: tools actually talk to never got the setting that lets RabbitMQ's user in from another machine,
#: and its NATS server was not running; two tools then measured nothing for thirty runs. So from
#: anywhere but the broker this now does the work on the broker, and then checks from here, the
#: way the tools will be answered, which is the only check that could have caught it.
brokers () {
  if [ -n "${BROKER_PRIV:-}" ] && ! ip -o -4 addr show 2>/dev/null | grep -q " ${BROKER_PRIV}/"; then
    log "== this is not the broker: setting the servers up on $BROKER_PRIV, where the tools reach them"
    #: The broker has a checkout but no hosts.env -- session.sh leaves that on the driver only --
    #: so its own address is handed over, or common.sh refuses to load there. And its checkout is
    #: brought up to date first: on 25 September it was eight commits behind this one, older than
    #: the setup it was being asked to run.
    remote_broker "cd sbl && { git pull -q --ff-only origin main || echo 'the broker could not pull; running the setup it has'; } && BROKER_PRIV=$BROKER_PRIV bash cloud/azure/tools.sh brokers" \
      || stop "setting the servers up on the broker failed; see above"
    local bad=0 tool why
    for tool in wrk2 valkey-benchmark rdkafka_performance rabbitmq-perftest nats-latency; do
      if why=$(server_answers "$tool"); then
        log "   from here, $tool's server answers it"
      else
        log "   from here, $tool's server does NOT answer it: $why"; bad=1
      fi
    done
    [ "$bad" = 0 ] || stop "a server the tools need does not answer them from here; see above"
    log "CAMPAIGN_COMPLETE: the tools block's servers are up, as the tools reach them"
    return 0
  fi
  brokers_here
}

brokers_here () {
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

  # RabbitMQ lets its default user in from the machine itself and nowhere else, which is the
  # right default and the wrong one here: the tools run on the driver and every broker in this
  # testbed is on the other machine, by design, so that a tool's messages cross the same wire
  # our own program's do. PerfTest therefore got ACCESS_REFUSED on every run and printed no
  # latency at all -- ten staircase steps of nothing, and a T2 that would not start for want of
  # the reference T1 never took. These brokers hold no data, answer only on the pair's own
  # private subnet, and live as long as the experiment, so the loopback restriction is lifted
  # rather than a credential invented for it.
  #: The directory is where RabbitMQ looks for extra configuration and it does not ship it.
  sudo mkdir -p /etc/rabbitmq/conf.d
  printf 'loopback_users = none\n' | sudo tee /etc/rabbitmq/conf.d/10-sbl.conf >/dev/null
  sudo systemctl enable --now nginx rabbitmq-server >/dev/null 2>&1
  sudo systemctl restart rabbitmq-server >/dev/null 2>&1
  sudo systemctl reload nginx >/dev/null 2>&1
  #: A unit, like nginx and RabbitMQ beside it. Started with nohup over a session, NATS did not
  #: outlive the session, and a broker restart left nothing to bring it back: every nats-latency
  #: run of 24 September found no server. One started the old way, or by hand as a transient
  #: unit of the same name, is stopped first so that it does not hold the port.
  if command -v nats-server >/dev/null; then
    sudo systemctl stop sbl-nats >/dev/null 2>&1
    sudo pkill -x nats-server >/dev/null 2>&1
    printf '[Unit]\nDescription=NATS for the tools block\nAfter=network.target\n\n[Service]\nExecStart=%s -p 4222\nRestart=always\n\n[Install]\nWantedBy=multi-user.target\n' \
      "$(command -v nats-server)" | sudo tee /etc/systemd/system/sbl-nats.service >/dev/null
    sudo systemctl daemon-reload
    sudo systemctl enable --now sbl-nats >/dev/null 2>&1
  fi

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
  local tool="$1" out="$2" backend id plan speedup me client=""
  case "$tool" in
    valkey-benchmark|memtier_benchmark) backend=redis ;;
    rdkafka_performance|kafka-end-to-end|kafka-producer-perf) backend=kafka ;;
    #: Our own clients for the protocols the study's program does not speak, written on
    #: 25 September because seven of the eleven tools had no reference at all, and T2 takes its
    #: offsets and its predictions from one. Each is timed the way its tools time, from inside the
    #: receiver's namespace like every tool here, and takes its settings as arguments: `sudo`
    #: clears the environment, which is how k6 came to make no request.
    vegeta|hey|k6|wrk2) client="http_reference.py --host $BROKER_PRIV --port 8080" ;;
    rabbitmq-perftest) client="amqp_reference.py --uri $RABBIT" ;;
    nats-latency) client="nats_reference.py --host $BROKER_PRIV --port 4222" ;;
    *) log "   no client of ours speaks $tool's protocol, so no reference is taken"; return 1 ;;
  esac
  if [ -n "$client" ]; then
    me=$(id -un)
    log "   our own client on the same path, for the reference: ${client%% *}"
    # shellcheck disable=SC2086
    $NETNS sudo -u "$me" timeout -k 30 900 python3 scripts/$client --rate "${RATE:-50}" \
      --seconds "${DURATION:-130}" --warmup-s 30 --out "$out/reference_trips.json" \
      > "$out/reference.log" 2>&1 \
      || { log "   WARN: the reference run timed nothing; see $out/reference.log"; return 1; }
    return 0
  fi
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

#: A stage will not run a tool the machine does not have.
#:
#: installed.json says what is here and, where something is not, why not. Running anyway is how
#: the Arm pair produced ten wrk2 folders whose readings are empty and whose whole output is
#: `exec of "wrk" failed: No such file or directory` -- the install had said MISSING, and the
#: jobs were queued for it regardless -- and three rabbitmq-perftest folders saying "no main
#: manifest attribute". Neither is a measurement, and neither announced itself as anything else.
have_tool () {
  local tool="$1" why
  why=$(python3 - "$DIR/installed.json" "$tool" <<'NOTHERE'
import json, sys
try:
    found = json.load(open(sys.argv[1]))
except Exception:
    raise SystemExit(0)
one = found.get(sys.argv[2])
if one is None or one.get("present"):
    raise SystemExit(0)
print(one.get("why") or "installed.json records it as not present")
raise SystemExit(1)
NOTHERE
) || stop "$tool is not installed on this machine: $why"
  #: The record says what the install found when it ran, which is not what is there now. The
  #: first x86 pair's record was written before the install learnt to ask whether a jar can be
  #: started, and it said yes to one that could not: fifteen runs of rabbitmq-perftest on
  #: 24 September printed "no main manifest attribute" and nothing else. So the one thing here
  #: that can be present and still not start is asked on the spot, whatever the record says.
  case "$tool" in
    rabbitmq-perftest)
      runnable_jar "${SBL_PERFTEST_JAR:-$HOME/tools/perf-test.jar}" \
        || stop "$tool's jar has no Main-Class, whatever installed.json says; rebuild it with: bash cloud/azure/tools.sh install" ;;
  esac
}

#: Does the server this tool talks to answer it, from here, the way the tool will be answered?
#:
#: On 24 September two of the eleven tools ran their whole T1, T3 and T4 -- fifteen runs each --
#: against servers that could not answer them, and printed nothing: nats-latency against a NATS
#: server that had died with the session that started it, and rabbitmq-perftest against a
#: RabbitMQ that let its user in from the broker itself only. Both had been certified a few hours
#: earlier by a check that asked 127.0.0.1 on the machine it ran on -- which was the driver.
#: This asks the broker, from the driver, and asks what the tool needs rather than whether a port
#: is open: a page of the right size, a PONG, a NATS greeting, a broker that lets the user in.
server_answers () {
  local tool="$1" host="${BROKER_PRIV:-}" got
  [ -n "$host" ] || { echo "no BROKER_PRIV here, so there is no broker to ask"; return 1; }
  case "$tool" in
    vegeta|hey|k6|wrk2)
      got=$(curl -s -o /dev/null -m 5 -w '%{http_code} %{size_download}' "http://$host:8080/")
      [ "$got" = "200 512" ] \
        || { echo "http://$host:8080/ answered '$got' where the fixed 512-byte page is 200 512"
             return 1; } ;;
    valkey-benchmark|memtier_benchmark)
      got=$(timeout 5 bash -c "exec 3<>/dev/tcp/${VALKEY_HOST:-$host}/6379 \
        && printf 'PING\r\n' >&3 && head -c 5 <&3" 2>/dev/null | tr -d '\r\n')
      [ "$got" = "+PONG" ] \
        || { echo "Redis at ${VALKEY_HOST:-$host}:6379 answered '$got' to PING"; return 1; } ;;
    rdkafka_performance|kafka-end-to-end|kafka-producer-perf)
      timeout 5 bash -c "echo > /dev/tcp/$host/19092" 2>/dev/null \
        || { echo "nothing listens for Kafka at $host:19092"; return 1; } ;;
    rabbitmq-perftest)
      timeout 5 bash -c "echo > /dev/tcp/$host/5672" 2>/dev/null \
        || { echo "nothing listens for AMQP at $host:5672"; return 1; }
      #: An open port is what fooled the check before. The user has to be let in from here, and
      #: RabbitMQ says whether it will be in one setting.
      timeout 20 ssh -n -i "$SSH_KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
        -o ConnectTimeout=10 "ubuntu@$host" "sudo rabbitmqctl environment 2>/dev/null" 2>/dev/null \
        | grep -q '{loopback_users,\[\]}' \
        || { echo "RabbitMQ on $host lets its user in from the broker only (loopback_users)"
             return 1; } ;;
    nats-latency)
      got=$(timeout 5 bash -c "exec 3<>/dev/tcp/$host/4222 && head -c 4 <&3" 2>/dev/null)
      [ "$got" = "INFO" ] \
        || { echo "no NATS greeting from $host:4222 (got '$got')"; return 1; } ;;
    *)
      echo "no check is written for $tool's server"; return 1 ;;
  esac
}

#: Every stage asks before it runs, because a server can go between one stage and the next: a
#: broker restarted under the session, a process that did not outlive it.
needs_server () {
  local why
  why=$(server_answers "$1") \
    || stop "$1's server does not answer it, so this stage would measure nothing: $why"
}

t1 () {
  local tool="${1:?which tool}"
  have_tool "$tool"
  needs_server "$tool"
  not_run_yet T1 "$tool" "t1-$tool-*ms/tool.txt"
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
  #: D25-5. The staircase assumed the delay reached the tool; this asks whether it did. A tool's
  #: reading should move with the delay once for every time its interval crosses the delayed
  #: direction, and k6's moved not at all -- it had made no request, which is how that was found.
  python3 scripts/tool_readings.py staircase --tool "$tool" --dir "$DIR" \
    --out "$DIR/t1-$tool-step.json" >/dev/null 2>&1
  local slope
  slope=$(python3 -c 'import json, sys
s = json.load(open(sys.argv[1]))["slope"]
if s["slope"] is None:
    print("no slope: too few steps reported")
else:
    print("%s moved %.3f per ms added, against %d crossing(s): %s" % (s["figure"], s["slope"],
          s["crossings"], "it measured the path" if s["measured_the_path"]
          else "IT DID NOT MEASURE THE PATH"))' "$DIR/t1-$tool-step.json" 2>/dev/null)
  log "   T1 slope: ${slope:-could not be read}"
  log "CAMPAIGN_COMPLETE: T1 $tool; its runs are under $DIR"
}

#: How many readings each measurement below takes. Each costs about two milliseconds.
FAKETIME_READS=12

#: One grammar's spelling of an offset given in milliseconds.
offset_as () {
  local grammar="$1" ms="$2"
  case "$grammar" in
    plain)   python3 -c "print('-%.9f' % (${ms} / 1000.0))" ;;
    seconds) python3 -c "print('-%.9fs' % (${ms} / 1000.0))" ;;
    *)       return 1 ;;
  esac
}

#: The median of (a real reading, then a faked one) under a spelling, in milliseconds. It carries
#: the cost of starting faketime and date as well as the offset, which is why it is only ever
#: used as a difference against the same measurement at no offset.
faketime_reading () {
  local spelling="$1" i before after vals=""
  for i in $(seq 1 "$FAKETIME_READS"); do
    before=$(date +%s.%N)
    after=$(faketime -f "$spelling" date +%s.%N 2>/dev/null) || return 1
    [ -n "$after" ] || return 1
    vals="$vals $(python3 -c "
import sys
print('%.6f' % ((float(sys.argv[1]) - float(sys.argv[2])) * 1000.0))" "$before" "$after")"
  done
  # shellcheck disable=SC2086
  python3 -c "
import statistics, sys
print('%.4f' % statistics.median(float(v) for v in sys.argv[1:]))" $vals 2>/dev/null
}

# The spelling of an offset that libfaketime actually honours, found by measuring it.
#
# libfaketime's units are days, hours, minutes and seconds. There is no millisecond one: it reads
# "-1.812ms" as 1.812 minutes and ignores the s, which moves the clock back 108 seconds rather
# than two milliseconds -- and that spelling was the first this tried. Fractional seconds are
# honoured, with or without a trailing s, and that is the grammar.
#
# The measurement was the other half of it. Reading the clock either side of a faked reading
# cannot confirm a millisecond offset, because starting faketime and date costs about two
# milliseconds here -- more than the offsets T2 uses -- so a correct spelling measured as
# anything at all, and T2 stopped with its offsets computed and nothing wrong with the machine.
# That cost is the same whatever offset is asked for, so it cancels in a difference: the same
# measurement is taken at no offset and at the wanted one, and what separates the two medians is
# the offset. On the first x86 pair that recovers 1.812 ms as 1.806 and 3.812 as 3.806.
#
# Nothing is run at an offset this could not confirm, because a T2 run with no offset looks
# exactly like a tool that handles negatives perfectly, and that is the one mistake this block
# cannot afford.
faketime_spelling () {
  local ms="$1" grammar zero here moved
  command -v faketime >/dev/null || return 1
  for grammar in plain seconds; do
    zero=$(faketime_reading "$(offset_as "$grammar" 0)") || continue
    here=$(faketime_reading "$(offset_as "$grammar" "$ms")") || continue
    [ -n "${zero:-}" ] && [ -n "${here:-}" ] || continue
    moved=$(python3 -c "
import sys
print('%.4f' % (float(sys.argv[1]) - float(sys.argv[2])))" "$here" "$zero") || continue
    #: Within a tenth of what was asked for, or 0.05 ms, whichever is the more forgiving.
    python3 -c "
import sys
moved, want = float(sys.argv[1]), float(sys.argv[2])
sys.exit(0 if abs(moved - want) <= max(0.1 * want, 0.05) else 1)" "$moved" "$ms" 2>/dev/null \
      || continue
    #: The spelling and what the clock was measured to do, on one line, because a caller
    #: reading this through $(...) reads it in a subshell: a variable set here never reaches
    #: them, and the first version set one, so every run recorded "measured ? ms".
    echo "$(offset_as "$grammar" "$ms") $moved"
    return 0
  done
  return 1
}

# T2: forced negatives. Move the clock the tool reads back by 0.5 ms and 2 ms, change nothing
# else, and ask what it did with the values that came out below zero.
#: T2 for the Go tools (D15-1): this machine's own clock, stepped early and put back.
#:
#: Go reads the clock without the C library, so libfaketime never reaches a Go tool, and the plan
#: has said since D15-1 what to do instead: a machine whose own clock is offset for the run and
#: restored afterwards. Until 25 September this script refused, and four tools had no T2. The
#: machine is the one the tools run on, and it must be doing nothing else: every process on it
#: sees the stepped clock. The step is measured against the hypervisor's PTP clock, which it does
#: not move (scripts/clock_step.py), and chrony is stopped only while the clock is held off.
STEPPED_MS=""
STEP_MOVED=""

machine_is_quiet () {
  ps -eo args --no-headers \
    | awk '/azure\/(campaign|stage0|stage1|chain)\.sh/ && !/awk/ { n++ } END { exit (n > 0) }'
}

#: Step early by ms, and leave in STEP_MOVED how far the clock was measured to move. Call it
#: directly, never through $(...): that is a subshell, and STEPPED_MS set there never reaches
#: unstep_clock. It was called that way on 25 September, so nothing was ever put back: each Go
#: tool's second offset landed on top of its first, 5.3 to 5.7 ms from the PTP clock where 3.8
#: was planned, and each next tool's control began with chrony still pulling the clock back.
step_clock () {  # ms, run dir
  local ms="$1" out="$2"
  sudo systemctl stop chrony || return 1
  sudo python3 scripts/clock_step.py shift --ms="-$ms" --out "$out/clock_step.json" \
    > /dev/null || { sudo systemctl start chrony; return 1; }
  STEPPED_MS="$ms"
  STEP_MOVED=$(python3 -c \
    'import json, sys; print("%.4f" % -json.load(open(sys.argv[1]))["moved_ms"])' \
    "$out/clock_step.json")
}

unstep_clock () {  # put the clock back, and chrony with it; safe to call when nothing is stepped
  if [ -n "$STEPPED_MS" ]; then
    sudo python3 scripts/clock_step.py shift --ms="$STEPPED_MS" > /dev/null 2>&1 \
      || log "   WARN: the clock could not be stepped back by $STEPPED_MS ms; chrony will pull it"
    STEPPED_MS=""
  fi
  sudo systemctl start chrony >/dev/null 2>&1
}

t2 () {
  local tool="${1:?which tool}" how=faketime
  have_tool "$tool"
  needs_server "$tool"
  not_run_yet T2 "$tool" "t2-$tool-*/tool.txt"
  case " $GO_TOOLS " in
    *" $tool "*)
      how=clock
      machine_is_quiet \
        || stop "$tool is a Go program, so T2 moves this machine's own clock, and a campaign is running here; every process on the machine would see the step"
      trap unstep_clock EXIT ;;
    *)
      case " $FAKEABLE " in
        *" $tool "*) ;;
        *) stop "$tool is not in either T2 list; add it to FAKEABLE or GO_TOOLS having checked which clock it reads" ;;
      esac
      sudo apt-get install -y -qq faketime >/dev/null 2>&1 ;;
  esac

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

  #: D23-1: the control. The same tool on the same traffic at no offset, taken here rather than
  #: borrowed from T1's zero step, which ran under a different arrangement of the delay and
  #: possibly hours earlier. It is what the two offset runs are held against, and without it
  #: "its figures did not move" cannot be told from "it did something none of the four
  #: describes" -- the two produced the same sentence until today.
  local control="$DIR/t2-$tool-control"
  mkdir -p "$control"
  log "   the control: no offset, on this machine in this state"
  bash cloud/azure/tools_run.sh "$tool" "$control" > "$control/tool.txt" 2>&1
  echo "$?" > "$control/exit_code.txt"
  python3 scripts/tool_readings.py read --tool "$tool" --file "$control/tool.txt" \
    --out "$control/reading.json" >/dev/null 2>&1 \
    || log "   the control reported no latency at all; the offset runs have nothing to move from"

  for ms in $offsets; do
    local run="t2-$tool-$(echo "$ms" | tr . _)ms"
    mkdir -p "$DIR/$run"
    local spelling moved said wrap
    if [ "$how" = clock ]; then
      step_clock "$ms" "$DIR/$run" \
        || stop "this machine's clock could not be stepped by $ms ms and measured against its PTP clock; T2 will not run an offset it cannot show reached the clock"
      moved="$STEP_MOVED"
      spelling="the system clock stepped"
      wrap=""
    else
      said=$(faketime_spelling "$ms") \
        || stop "no libfaketime offset of $ms ms could be confirmed on this machine; T2 will not run an offset it cannot show reached the clock"
      spelling="${said%% *}"; moved="${said##* }"
      wrap="faketime -f $spelling"
    fi
    echo "$spelling" > "$DIR/$run/offset_spelling.txt"
    #: What the clock was measured to actually do under that spelling, beside what was asked for,
    #: because "confirmed" is a claim and this is the number behind it.
    echo "{\"asked_ms\": $ms, \"measured_ms\": $moved, \"spelling\": \"$spelling\"}" \
      > "$DIR/$run/offset_measured.json"
    log "   $ms ms, as $spelling, measured $moved ms"
    SBL_TOOL_WRAP="$wrap" bash cloud/azure/tools_run.sh "$tool" "$DIR/$run" \
      > "$DIR/$run/tool.txt" 2>&1
    echo "$?" > "$DIR/$run/exit_code.txt"
    #: Put back before anything else happens, reading included: the clock is held off only for as
    #: long as the tool runs.
    if [ "$how" = clock ]; then
      unstep_clock
      #: And checked, with the answer beside the run. On 25 September nothing was put back and
      #: nothing said so; the only sign was the offset printed once, at the very end.
      local back
      back=$(sudo python3 scripts/clock_step.py measure) || back=""
      echo "{\"after_putting_back_ms\": ${back:-null}}" > "$DIR/$run/clock_back.json"
      log "   the clock put back: ${back:-not measured} ms from the PTP clock"
      python3 -c 'import sys; sys.exit(0 if abs(float(sys.argv[1])) <= 0.25 else 1)' \
        "${back:-99}" \
        || stop "the clock is ${back:-an unmeasured number of} ms from the PTP clock after being put back; T2 will not run on from a clock still held off"
    fi
    python3 scripts/tool_readings.py read --tool "$tool" --file "$DIR/$run/tool.txt" \
      --out "$DIR/$run/reading.json" >/dev/null 2>&1 \
      || log "   it reported no latency at all under the offset; kept as that"
    # Our own trips for the same messages are the reference the verdict is measured against;
    # T1's zero-delay reading of the same tool is what cancels that tool's own bias out of the
    # comparison, and T1's measured step is what the prediction passes through.
    #: The reference is T1's, taken at the zero step on the same path, and it is read from where
    #: T1 wrote it. This looked for it inside the T2 run's own folder, where nothing puts it, so
    #: the condition could never be true and every T2 run ended with "no reference trips beside
    #: this run" -- a warning about a file that was never meant to be there.
    if [ -s "$trips" ]; then
      python3 scripts/tool_negatives.py judge --reading "$DIR/$run/reading.json" \
        --reference "$trips" --offset-ms "$ms" \
        --plain "$plain" ${step:+--step-ms "$step"} \
        ${moved:+--shift-ms "$moved"} \
        $([ -s "$control/reading.json" ] && printf -- "--control %s" "$control/reading.json") \
        $([ -s "$DIR/$run/asked_to_send.txt" ] && printf -- "--sent %s" "$(cat "$DIR/$run/asked_to_send.txt")") \
        --staircase "$DIR" --tool "$tool" \
        --exit-code "$(cat "$DIR/$run/exit_code.txt")" --out "$DIR/$run/verdict.json" \
        || log "   UNDECIDED at $ms ms; see $DIR/$run/verdict.json"
    else
      log "   WARN: T1 left no reference trips at $trips, so nothing can be judged from it"
    fi
  done
  log "CAMPAIGN_COMPLETE: T2 $tool; its runs are under $DIR"
}

# T3: idle against 88% load, with and without go-first priority on the tool's own process.
t3 () {
  local tool="${1:?which tool}"
  have_tool "$tool"
  needs_server "$tool"
  not_run_yet T3 "$tool" "t3-$tool-*/tool.txt"
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
      #: -9, as campaign.sh learnt on 23 September: stress-ng does not stop for a TERM here, so
      #: the wait sat until its own --timeout 600s, and every 88% step of T3 took ten minutes for
      #: a one-minute run. The measurement had finished long before; only the time was lost.
      [ "$load" != 0 ] && { kill -9 "$stress" 2>/dev/null; wait "$stress" 2>/dev/null
                            pkill -9 -x stress-ng 2>/dev/null; }
      log "   load $load%, go-first $first done"
    done
  done
  log "CAMPAIGN_COMPLETE: T3 $tool; its runs are under $DIR"
}

# T4: which trips the tool can report at all, confirmed from a real output file.
t4 () {
  local tool="${1:?which tool}"
  have_tool "$tool"
  needs_server "$tool"
  not_run_yet T4 "$tool" "t4-$tool/tool.txt"
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
