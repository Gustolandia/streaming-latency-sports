#!/usr/bin/env bash
# A pair's own list of work, which it keeps going through on its own -- across its own reboots.
#
# chain.sh keeps one campaign going after its calibration, on the driver, so that a closing laptop
# cannot cost a pair its night. It cannot do the same for a *session*, because a session begins by
# booting a different kernel or a different core count, and a machine cannot ssh into itself to
# reboot itself and carry on. So the twelve A2 sessions and the two A5 sessions were driven from
# outside, and on 21 September that outside was a background job in a chat session: it died with
# the session, twice, and each time the pair went quiet until somebody noticed.
#
# The way out is for the machine to leave itself a note before it reboots and read it when it
# comes back. That is all this is. A job list on disk, a phase beside it, and an @reboot line that
# starts the loop again. Nothing outside the pair has to stay alive, or awake, or connected.
#
#     bash cloud/azure/queue.sh add "boot=hz1000 backend=kafka c0=2 block=A2 rounds=4 anchor=3"
#     bash cloud/azure/queue.sh start      # installs the @reboot line and starts the loop
#     bash cloud/azure/queue.sh show       # what it has done and what is left
#     bash cloud/azure/queue.sh stop       # after the job it is on, and takes the line out
#
# A job is one line of key=value:
#
#   boot=      hz1000 | hz250 | hz100 | stock | cpu2 | cpu4 | cpu8 | none
#              none is the only one that does not reboot; stock reboots onto the pinned default
#   block=     the campaign to run when the machine is back up (A2, A5, A4, ...). Leave it out,
#              with boot=none, for a job that starts nothing and only waits for the session
#              already on the pair -- which is how a list is put on a machine mid-session.
#   backend=   kafka | redis, passed to both the campaign and the rounds simulation
#   rounds=    how many, or leave it out and give rounds-from=
#   c0=        rounds of the session's own delay calibration (default 2)
#   up=        how far that calibration reaches, in ms (default: worked out from the tick)
#   load=      the load it calibrates at (default 75)
#   slices=    passed on to stage 1, e.g. 3,1.5
#   anchor=    the anchor slice
#   clients=   "python java", for a session that opens A8
#   cmd=       a command to run instead of a campaign, for work no calibration places -- the
#              tools block. It holds spaces, so it takes the rest of the line.
#   note=      the rounds note. It holds spaces, so it takes the rest of the line.
#
# A job carries at most one of cmd= and note=, and whichever it carries comes last.
#
# It does not stop the queue when a job stops itself. That was the earlier rule and it is the
# wrong one here: a campaign that trips a brake has still measured everything up to the trip, the
# next job is a different kernel and a different question, and a queue that halts on the first
# one turns a stopped campaign into a stopped night. The job is recorded as stopped, put back on
# the end of the list once, and the queue goes on. What it will not do is retry in place, which
# is how one bad session becomes a hundred.
#
# Like every campaign script here, it carries on past a failing command on purpose: a failure has
# to be reported rather than vanish.
. "$(dirname "${BASH_SOURCE[0]}")/../campaigns/common.sh"
set +e
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)" || exit 1

DIR="runs/azure/queue"
JOBS="$DIR/jobs.txt"
AT="$DIR/at"
PHASE="$DIR/phase"
BOOTS="$DIR/boots"
SEEN="$DIR/seen"
RETRIED="$DIR/retried"
STOPFILE="$DIR/stop"
LOG="$DIR/log"
LOCK="$DIR/lock"
#: The copy the loop actually runs from, beside this file so its `..` still reaches campaigns/.
RUNNING_NAME=".queue.running.sh"
mkdir -p "$DIR"

# Plain, because both ways the loop is started send its output to the log, and a tee as well as
# that redirect wrote every line twice. The one line printed outside the loop tees for itself.
log () { echo "$(date -u +%FT%TZ) queue: $*"; }

# The addresses and the key come from common.sh, which reads the pair's own hosts.env -- the copy
# session.sh left on the driver, not the one on the computer that started the session.
SSH_OPTS=(-i "$SSH_KEY" -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=20)
brk () { ssh "${SSH_OPTS[@]}" "ubuntu@$BROKER_PRIV" "$@"; }

#: One field out of a job line. Two keys hold sentences rather than words -- the rounds note and
#: a command -- so each takes the rest of the line, and a job carries at most one of them.
field () {
  local line="$1" key="$2"
  # Its own statement: bash expands every word of a `local` before it runs any of them, so
  # head="$line" on the line that declares `line` reads whatever `line` meant outside -- nothing,
  # and under the set -u this kit runs with, that is fatal rather than merely wrong.
  local head="$line"
  head="${head%%note=*}"
  head="${head%%cmd=*}"
  case "$key" in
    note|cmd) case "$line" in *"$key="*) echo "${line#*"$key="}" ;; *) echo "" ;; esac ;;
    *) local t=" $head "
       case "$t" in
         *" $key="*) t="${t#*" $key="}"; echo "${t%% *}" ;;
         *) echo "" ;;
       esac ;;
  esac
}

#: How far a session's calibration has to reach. A2's longest point is f2sh, twice the slice plus
#: twice the tick, and its longest slice is 3 ms; the calibration's steps double, so this is the
#: first power of two at or above it. Wrong does not fail loudly -- the design quietly drops the
#: setups it cannot reach -- so it is computed rather than typed. Same arithmetic as a2_session.sh.
reach_ms () {
  local boot="$1" hz=1000 tick longest up
  case "$boot" in hz1000) hz=1000 ;; hz250) hz=250 ;; hz100) hz=100 ;; *) hz=250 ;; esac
  tick=$(( 1000 / hz ))
  longest=$(( 2 * 3 + 2 * tick ))
  up=8
  while [ "$up" -lt "$longest" ]; do up=$(( up * 2 )); done
  echo "$up"
}

read_at    () { [ -s "$AT" ] && cat "$AT" || echo 1; }
read_phase () { [ -s "$PHASE" ] && cat "$PHASE" || echo prep; }
job_line   () { sed -n "$(read_at)p" "$JOBS" 2>/dev/null; }
job_count  () { grep -c . "$JOBS" 2>/dev/null || echo 0; }

set_phase () { echo "$1" > "$PHASE"; }
advance   () { echo $(( $(read_at) + 1 )) > "$AT"; set_phase prep; echo 0 > "$BOOTS"; }

#: Put a job that stopped itself back on the end, once. Twice would be a retry loop wearing a
#: different hat, and the second failure of the same job is information rather than bad luck.
requeue_once () {
  local line="$1"
  if grep -qxF "$line" "$RETRIED" 2>/dev/null; then
    log "not queueing it again; it has already had its second go"
  else
    echo "$line" >> "$RETRIED"
    echo "$line" >> "$JOBS"
    log "put back on the end of the list for one more go"
  fi
}

#: Steps 6 to 8 of session.sh, which are the ones a reboot undoes. The brokers live on the other
#: machine and do not reboot with this one, but they are restarted anyway because a broker that
#: died quietly looks exactly like one that is fine until a campaign reads no messages. The
#: receiver's namespace is on this machine and never survives.
rebuild_session () {
  log "  rebuilding the session the reboot took"
  brk "cd sbl && sudo python3 scripts/receiver_delay.py broker-clear --apply >/dev/null \
    && sudo bash cloud/brokers.sh $BROKER_PRIV" >/dev/null 2>&1 \
    || { log "  the brokers did not come back"; return 1; }
  sudo python3 scripts/receiver_delay.py driver \
    --address "$RECEIVER_IP/$SUBNET_PREFIX" --gateway "$SUBNET_GATEWAY" --apply >/dev/null 2>&1 \
    || { log "  the receiver's namespace did not come back"; return 1; }
  local stamp; stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p runs/azure_settings
  sudo python3 scripts/sched_settings.py read \
    > "runs/azure_settings/${AZ_PROFILE}_driver_$stamp.json" 2>/dev/null
  brk "cd sbl && sudo python3 scripts/sched_settings.py read" \
    > "runs/azure_settings/${AZ_PROFILE}_broker_$stamp.json" 2>/dev/null
  return 0
}

#: What the machine has to look like before a campaign is placed on it. A session that reached its
#: core count or its tick some other way than the one asked for would not fail; it would run, and
#: it would be filed under a name that is not true.
verify_boot () {
  local boot="$1" running; running="$(uname -r)"
  case "$boot" in
    none) return 0 ;;
    stock) case "$running" in *sbl*) log "  wanted the stock kernel and this is $running"; return 1 ;; esac ;;
    hz*)   local hz="${boot#hz}"
           case "$running" in *"sbl$hz") ;; *) log "  wanted HZ=$hz and this is $running"; return 1 ;; esac
           bash cloud/azure/kernels.sh check "$hz" >/dev/null 2>&1 \
             || { log "  HZ=$hz did not pass its checks"; return 1; } ;;
    cpu*)  local n="${boot#cpu}"
           # cpus.sh builds its entry on the stock kernel by name, so this should hold; it is
           # checked because the count check would not catch it. A5 belongs with A1, A3 and A7
           # on the stock kernel, and a reduced-count session on a tick build would pass every
           # check it is given and answer a question nobody asked.
           case "$running" in *sbl*) log "  $n CPUs but on $running, and A5 runs on the stock kernel"; return 1 ;; esac
           bash cloud/azure/cpus.sh check "$n" >/dev/null 2>&1 \
             || { log "  the machine did not come up with $n CPUs"; return 1; } ;;
  esac
  return 0
}

#: Ask for the boot. Everything here happens before the reboot, and none of it is the reboot.
ask_for_boot () {
  local boot="$1"
  case "$boot" in
    none|stock) return 0 ;;
    hz*)  bash cloud/azure/kernels.sh boot "${boot#hz}" >/dev/null 2>&1 ;;
    cpu8) bash cloud/azure/cpus.sh restore >/dev/null 2>&1 ;;
    cpu*) bash cloud/azure/cpus.sh boot "${boot#cpu}" >/dev/null 2>&1 ;;
  esac
}

#: Bring the checkout up to date, at the one moment in a job when nothing is measuring.
#
# A pair driven by this queue ran whatever code it had when the list was put on it, for as long
# as the list lasted: the block jobs go straight to stage0.sh and chain.sh, and only the cmd=
# jobs pulled, because their commands say so. matched-b sat four commits behind for a day that
# way, including the one that corrects a campaign's load to the load the machine shows, and the
# watch's "the lanes run different commits" was saying so every five minutes.
#
# Here, and nowhere else: after the boot is verified and before a calibration or a campaign is
# placed. --ff-only so a tree somebody has edited on the machine stops rather than merges, and a
# failure is a line in the log, not a stopped job -- the code it has is the code that ran the
# last job, and running the next one with it beats a pair that goes quiet.
pull_code () {
  local before after
  before="$(git rev-parse --short HEAD 2>/dev/null)"
  if git pull --ff-only -q origin main 2>/dev/null; then
    after="$(git rev-parse --short HEAD 2>/dev/null)"
    [ "$before" = "$after" ] && log "  code is current at $after" || log "  code $before -> $after"
  else
    log "  the code could not be brought up to date; carrying on at $before"
  fi
}

start_job () {
  local line="$1"
  local boot block backend rounds c0 up load slices anchor clients note
  boot="$(field "$line" boot)";       block="$(field "$line" block)"
  # A job with no block of its own starts nothing and only waits for what is already on the pair.
  # It is how a list is put on a machine that is in the middle of a session: without it the queue
  # would take its first job straight away and reboot under a running calibration, which is the
  # one thing that went wrong twice on 21 September.
  if [ -z "$block" ]; then
    log "  nothing of its own to start; waiting for the pair to go quiet"
    return 0
  fi
  backend="$(field "$line" backend)"; rounds="$(field "$line" rounds)"
  c0="$(field "$line" c0)";           up="$(field "$line" up)"
  load="$(field "$line" load)";       slices="$(field "$line" slices)"
  anchor="$(field "$line" anchor)";   clients="$(field "$line" clients)"
  note="$(field "$line" note)"
  [ -n "$c0" ]   || c0=2
  [ -n "$load" ] || load=75
  [ -n "$up" ]   || up="$(reach_ms "$boot")"
  # A5's core count has to reach three places: the boot that sets it, the calibration measured on
  # that boot, and the design that writes the runs. All three come off the one word here, because
  # the two that could disagree are the two that do not fail loudly -- a campaign designed for
  # eight CPUs on a machine booted with two would run, and be filed under a name that is not true.
  local cores=""
  case "$boot" in cpu*) cores="${boot#cpu}" ;; esac

  verify_boot "$boot" || return 1
  pull_code
  rebuild_session || return 1

  local earlier
  earlier=$(for d in runs/azure/stage0/*_*; do
              [ -s "$d/shakedown.json" ] || continue
              python3 -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("ok") else 1)' \
                "$d/shakedown.json" 2>/dev/null && echo "$d"
            done | tail -1)
  [ -n "$earlier" ] || { log "  no stage 0 folder with a passing shakedown to start from"; return 1; }

  # Remembered before anything starts, because "the newest folder" is the last campaign's until
  # this one makes its own, and reading it is how a finished session was mistaken for this one
  # twice on 21 September.
  ls -d runs/azure/stage1/*/ 2>/dev/null | sort > "$SEEN"

  log "  calibration from $earlier, reaching $up ms, $c0 round(s), load $load${cores:+, $cores CPUs}"
  UP_TO_MS="$up" LOAD_PCT="$load" C0_ROUNDS="$c0" CLIENTS="$clients" CPUS="$cores" \
    setsid nohup bash cloud/azure/stage0.sh session "$earlier" > stage0.log 2>&1 < /dev/null &
  sleep 15
  grep -q "stage 0 on" stage0.log 2>/dev/null \
    || { log "  the calibration did not start; read stage0.log"; return 1; }

  local args=("$block")
  [ -n "$rounds" ]  && args+=(--rounds "$rounds")
  [ -n "$note" ]    && args+=(--rounds-note "$note")
  [ -n "$backend" ] && args+=(--backend "$backend")
  [ -n "$slices" ]  && args+=(--slices "$slices")
  [ -n "$anchor" ]  && args+=(--anchor-slice "$anchor")
  [ -n "$cores" ]   && args+=(--cores "$cores")
  log "  campaign: ${args[*]}"
  setsid nohup bash cloud/azure/chain.sh "${args[@]}" > chain.log 2>&1 < /dev/null &
  sleep 10
  grep -q "chain:" chain.log 2>/dev/null \
    || { log "  the chain did not start; read chain.log"; return 1; }
  return 0
}

#: Is any of the pair's work still going? What a job of its own is waiting for is a word in a
#: log, but a job that only holds the list back cannot use that: the session it is waiting for
#: may already have made its folder, in which case there is no new one coming and the wait would
#: run to its twelve-hour limit. What it is really waiting for is the machine, so it asks the
#: machine. Read here rather than over ssh, so there is no command line carrying the pattern for
#: it to match itself in -- which killed three connections this week.
work_running () {
  ps -eo args --no-headers \
    | awk '/azure\/(campaign|stage0|stage1|chain)\.sh/ && !/awk/ { n++ } END { exit !(n > 0) }'
}

#: How the campaign this job started ended. Only a folder that was not there when it started
#: counts as its own.
campaign_state () {
  local d log_file last
  while read -r d; do
    [ -n "$d" ] || continue
    grep -qxF "$d" "$SEEN" 2>/dev/null && continue
    log_file=$(ls "$d"campaign_*.log 2>/dev/null | head -1)
    [ -n "$log_file" ] || continue
    last=$(tail -1 "$log_file" 2>/dev/null)
    case "$last" in
      *CAMPAIGN_COMPLETE*) echo "done $d"; return ;;
      *STOP_RULE*)         echo "stopped $d"; return ;;
    esac
  done < <(ls -d runs/azure/stage1/*/ 2>/dev/null | sort)
  last=$(tail -1 chain.log 2>/dev/null)
  case "$last" in *STOP_RULE*) echo "stopped chain.log"; return ;; esac
  echo "running"
}

run_loop () {
  local line boot state waited
  # The @reboot line calls this directly, and the first reboot of the first job can happen before
  # anything has written these, so the loop starts them rather than assuming start did.
  [ -s "$AT" ] || echo 1 > "$AT"
  [ -s "$PHASE" ] || echo prep > "$PHASE"
  while true; do
    [ -e "$STOPFILE" ] && { log "asked to stop; the list is left where it is"; return 0; }
    line="$(job_line)"
    if [ -z "$line" ]; then
      log "every job on the list has run ($(job_count) of them)"
      #: And if the list was armed to, the pair turns itself off here rather than billing
      #: until somebody notices. This is the one place it can be done safely: the list is
      #: exhausted, which is true only after the jobs put back for a second go have run
      #: too, and the stop file is handled above, so a pair asked to stop keeps its list.
      if [ -e "$DIR/stop_when_done" ]; then
        log "the list is armed to stop the pair when it ends; asking Azure now"
        bash cloud/azure/stop_self.sh 2>&1 | while read -r said; do log "  $said"; done
      fi
      return 0
    fi
    boot="$(field "$line" boot)"
    case "$(read_phase)" in
      prep)
        log "== job $(read_at) of $(job_count): $line"
        local n; n=$(( $( [ -s "$BOOTS" ] && cat "$BOOTS" || echo 0 ) + 1 ))
        echo "$n" > "$BOOTS"
        if [ "$n" -gt 2 ]; then
          log "  it has been rebooted twice for this job already; going on to the next"
          advance; continue
        fi
        ask_for_boot "$boot"
        set_phase booted
        if [ "$boot" = none ]; then
          log "  no reboot needed"
          continue
        fi
        log "  asked for $boot; rebooting"
        sync
        sudo systemctl reboot
        sleep 120          # the machine is going down; @reboot picks the loop up again
        return 0
        ;;
      booted)
        log "  up on $(uname -r)"
        local cmd; cmd="$(field "$line" cmd)"
        if [ -n "$cmd" ]; then
          # The tools block is not a campaign: no calibration places it and no chain waits on
          # one, so a job can simply be a command. It is run here rather than let go of, because
          # this loop is already the thing that survives, and a command that outlives it would
          # have nobody to tell.
          local out rc
          out="$DIR/cmd-$(read_at).log"
          if verify_boot "$boot"; then
            log "  running: $cmd"
            #: The log is appended to, so that a job put back on the list keeps what its first
            #: attempt said, and so that a list rewritten around a job does not throw away the
            #: log of whatever held that number before. That costs a header: without one, the
            #: top of cmd-12.log was an error from a different job hours earlier, and it was
            #: read as this one's -- twice.
            echo "=== $(date -u +%FT%TZ) job $(read_at): $cmd" >> "$out"
            timeout 43200 bash -c "$cmd" >> "$out" 2>&1
            rc=$?
            log "  it finished with status $rc; its output is in $out"
            [ "$rc" = 0 ] || requeue_once "$line"
          else
            log "  STOPPED before it ran: job $(read_at)"
            requeue_once "$line"
          fi
          advance
        elif start_job "$line"; then
          set_phase waiting
        else
          log "  STOPPED before it ran: job $(read_at)"
          requeue_once "$line"
          advance
        fi
        ;;
      waiting)
        waited=0
        while true; do
          if [ -z "$(field "$line" block)" ]; then
            if work_running; then state="running"; else state="done the pair is quiet"; fi
          else
            state="$(campaign_state)"
          fi
          case "$state" in
            done*)    log "  finished: ${state#done }"; advance; break ;;
            stopped*) log "  stopped itself: ${state#stopped }"; requeue_once "$line"; advance; break ;;
          esac
          sleep 60
          waited=$(( waited + 1 ))
          # Twelve hours. The longest job on any list here is about five, and a job that has not
          # said either word in twelve is not going to.
          if [ "$waited" -ge 720 ]; then
            log "  nothing from it in 12 hours; going on to the next"
            requeue_once "$line"; advance; break
          fi
        done
        ;;
    esac
  done
}

CMD="${1:-show}"
case "$CMD" in
  add)
    [ -n "${2:-}" ] || { echo "usage: queue.sh add \"boot=... block=... rounds=...\"" >&2; exit 2; }
    echo "$2" >> "$JOBS"
    echo "added as job $(job_count)"
    ;;
  start)
    rm -f "$STOPFILE"
    [ -s "$AT" ] || echo 1 > "$AT"
    [ -s "$PHASE" ] || echo prep > "$PHASE"
    line="@reboot sleep 60 && cd $PWD && flock -n $PWD/$LOCK bash cloud/azure/queue.sh run >> $PWD/$LOG 2>&1"
    ( crontab -l 2>/dev/null | grep -v "queue.sh run"; echo "$line" ) | crontab -
    log "the @reboot line is in; starting the loop" | tee -a "$LOG"
    setsid nohup flock -n "$LOCK" bash cloud/azure/queue.sh run >> "$LOG" 2>&1 < /dev/null &
    sleep 4
    # Asked for, then checked. A lock left behind by a loop that was killed is held by nothing and
    # still refuses the next one, and flock says so by exiting quietly -- so this said "running"
    # over a queue that was not, and a pair sat idle through its whole tools block on 22 September
    # before the watch stopped it. Whether it is running is a thing to look at, not to assume.
    # The loop runs from a copy of this file, so what to look for is the copy's name too.
    if ps -eo args --no-headers | awk '/queue[^ ]*\.sh run/ && !/awk/ { found = 1 } END { exit !found }'
    then
      echo "running; watch it with: tail -f $LOG"
    else
      echo "FAILED to start: nothing is running the list." >&2
      echo "  Most likely $LOCK is held by a loop that has since died; remove it and try again." >&2
      exit 1
    fi
    ;;
  run)
    # The loop pulls, and a pull rewrites the file bash is reading. Bash reads a script as it
    # goes and keeps its place by byte offset, so a loop that replaces its own source can carry
    # on in the middle of something else. It runs from a copy instead, taken before any pull can
    # happen; the copy sits beside the original so that the common.sh it sources is still one
    # directory up, and it is retaken every time this is started -- which is every reboot, since
    # that is what the @reboot line calls.
    if [ "$(basename "${BASH_SOURCE[0]}")" != "$RUNNING_NAME" ]; then
      cp "${BASH_SOURCE[0]}" "$(dirname "${BASH_SOURCE[0]}")/$RUNNING_NAME" || exit 1
      exec bash "$(dirname "${BASH_SOURCE[0]}")/$RUNNING_NAME" run
    fi
    run_loop ;;
  stop)
    touch "$STOPFILE"
    crontab -l 2>/dev/null | grep -v "queue.sh run" | crontab - 2>/dev/null
    echo "it will stop after the job it is on; the @reboot line is out"
    ;;
  arm-stop)
    touch "$DIR/stop_when_done"
    echo "armed: this pair deallocates itself once every job on the list has run"
    ;;
  disarm-stop)
    rm -f "$DIR/stop_when_done"
    echo "disarmed: the pair stays up when the list ends"
    ;;
  show)
    echo "jobs: $(job_count), on job $(read_at), phase $(read_phase)"
    [ -s "$JOBS" ] && nl -ba "$JOBS"
    echo "--- the last of its log ---"
    tail -15 "$LOG" 2>/dev/null
    ;;
  *) echo "usage: queue.sh add|start|run|stop|show|arm-stop|disarm-stop" >&2; exit 2 ;;
esac
