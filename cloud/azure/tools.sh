#!/usr/bin/env bash
# The tools block: install the tools at the versions the audit read, and run T1 to T4.
#
# Each runnable tool is one campaign on one machine pair, with our own program recording the same
# messages, so every number a tool reports has a reference measured beside it. The versions are
# pinned before any run because a tool's behaviour is what T1 to T4 report, and a tool that
# changed under us would be a different experiment (the plan's Section "The tools").
#
#     bash cloud/azure/tools.sh brokers          # the servers the tools need, on the broker host
#     bash cloud/azure/tools.sh install          # pinned versions, fingerprints recorded
#     bash cloud/azure/tools.sh t1 vegeta        # the delay staircase
#     bash cloud/azure/tools.sh t2 wrk2          # forced negatives, by moving the clock it reads
#     bash cloud/azure/tools.sh t3 vegeta        # idle against 88% load, with and without go-first
#     bash cloud/azure/tools.sh t4 vegeta        # what it can report at all
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
PINNED='
vegeta|go|cf5811269046c672a604b1eb352204d30f9d5b58
hey|go|5626f79b8698df6daf9b25799c9805c6ac7dbd9e
k6|go|3fcf5388d78c
valkey-benchmark|apt|9.1.2
memtier_benchmark|git|5694a3d61aaf0322a62fc44083ba6f21305de40e
rdkafka_performance|git|6f86c853a131d66fc2cd2a44aac99e83de6c2337
kafka-end-to-end|kafka|995cfcf99f7917403e030428c00b5c518089d1b2
kafka-producer-perf|kafka|995cfcf99f7917403e030428c00b5c518089d1b2
wrk2|git|resolve
rabbitmq-perftest|jar|resolve
nats-latency|go|resolve
'

#: The tools libfaketime can reach, because they read the clock through the C library.
FAKEABLE="wrk2 valkey-benchmark memtier_benchmark rdkafka_performance kafka-end-to-end \
kafka-producer-perf rabbitmq-perftest"
#: The tools it cannot: Go does not go through the C library for the clock.
GO_TOOLS="vegeta hey k6 nats-latency"

install () {
  log "== the tools, at the versions the audit read"
  sudo apt-get update -qq || stop "apt-get update failed"
  sudo apt-get install -y -qq golang-go build-essential git pkg-config libssl-dev \
      libevent-dev autoconf automake libpcre3-dev zlib1g-dev valkey-tools \
    || log "WARN: some packages were not available; each tool is checked below"

  echo "$PINNED" | while IFS='|' read -r tool how version; do
    [ -n "$tool" ] || continue
    if [ "$version" = resolve ]; then
      log "   $tool: $how, NOT YET PINNED -- what is installed is recorded below"
    else
      log "   $tool: $how, pinned at $version"
    fi
  done

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
t1 () {
  local tool="${1:?which tool}"
  local steps="0 0.1 0.2 0.3 0.5 0.7 0.9 1.1 1.5 2.0"
  local order; order=$(echo $steps | tr ' ' '\n' | shuf | tr '\n' ' ')
  log "== T1 $tool: the delay staircase, in the order $order"
  for ms in $order; do
    local run="t1-$tool-$(echo "$ms" | tr . _)ms"
    mkdir -p "$DIR/$run"
    sudo python3 scripts/receiver_delay.py broker --delay-ms "$ms" --apply \
      > "$DIR/$run/delay.json" 2>&1 || stop "the $ms ms delay could not be applied"
    bash cloud/azure/tools_run.sh "$tool" "$DIR/$run" > "$DIR/$run/tool.txt" 2>&1
    python3 scripts/tool_readings.py read --tool "$tool" --file "$DIR/$run/tool.txt" \
      --out "$DIR/$run/reading.json" >/dev/null 2>&1 \
      || log "WARN: $tool reported no latency at $ms ms; kept as a reading of nothing"
    log "   $ms ms done"
  done
  sudo python3 scripts/receiver_delay.py broker-clear --apply >/dev/null 2>&1
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
  for load in 0 88; do
    for first in no yes; do
      local run="t3-$tool-l$load-first$first"
      mkdir -p "$DIR/$run"
      local wrap=""
      [ "$first" = yes ] && wrap="sudo chrt -f 80"
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
  bash cloud/azure/tools_run.sh "$tool" "$DIR/$run" > "$DIR/$run/tool.txt" 2>&1
  python3 scripts/tool_readings.py read --tool "$tool" --file "$DIR/$run/tool.txt" \
    --out "$DIR/$run/reading.json" >/dev/null 2>&1 \
    || stop "$tool printed no latency at all, so T4 has nothing to confirm from"
  python3 -c 'import json,sys
r = json.load(open(sys.argv[1]))
print("   reports: %s" % ", ".join(sorted(r["reported_ms"])))
print("   its own step: %s ms" % r["step_ms"])' "$DIR/$run/reading.json"
  log "CAMPAIGN_COMPLETE: T4 $tool; see $DIR/$run/reading.json"
}

case "${1:-}" in
  brokers) brokers ;;
  install) install ;;
  t1) t1 "${2:-}" ;;
  t2) t2 "${2:-}" ;;
  t3) t3 "${2:-}" ;;
  t4) t4 "${2:-}" ;;
  *) echo "usage: bash cloud/azure/tools.sh brokers | install | t1 <tool> | t2 <tool> |" >&2
     echo "       t3 <tool> | t4 <tool>" >&2
     exit 2 ;;
esac
