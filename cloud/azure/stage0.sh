#!/usr/bin/env bash
# Stage 0 of the frozen experiment plan (freeze 02) on one machine pair, from start to end,
# unattended.
#
# Run on the driver, from the checkout, after cloud/azure/session.sh:
#     nohup bash cloud/azure/stage0.sh first > stage0.log 2>&1 &   # the first x86 pair
#     nohup bash cloud/azure/stage0.sh new > stage0.log 2>&1 &     # the second x86 pair, or Arm
# A pair that passed its shakedown in an earlier session skips the long parts of the pilot when
# that session's stage-0 folder is named. The network part runs again all the same, because a
# start after a stop can put a machine on another physical host:
#     nohup bash cloud/azure/stage0.sh new runs/azure/stage0/<profile>_<start> > stage0.log 2>&1 &
#
# In order, each step only if the ones before it succeeded:
#   1. pilot  cloud/azure/pilot.sh: the pair's shakedown. Its settings, network (the broker holds
#             replies for the set delay, and to the receiver alone), load and never-negative
#             checks must pass (scripts/pilot_checks.py shakedown), or nothing else runs. The two
#             paths are measured by ping, TCP and UDP and recorded, not required (plan v7).
#             With an earlier folder, only the network part runs, and its delay check must pass.
#   2. C0     the session's delay calibration. On the first pair it is the staircase S0-1: steps
#             up to 16 ms, 4 rounds. On a new pair: up to 8 ms, 2 rounds, and 2 more when the fit
#             finds the calibration too loosely known and nothing else wrong.
#   3. fit    scripts/delay_calibration.py fit over the session's C0 queues, with its gate.
#   4. B0     the baseline trips. They need no calibration, so they run whatever the gate said.
#   5. P0     the spread pilot, placed from the calibration, and only if its gate passed. A
#             failed gate ends the session, and the pair starts a new one with a new C0.
#
# KIND session runs steps 1 to 3 and stops: a pair that has already finished stage 0 needs its own
# calibration for the session ahead, because a machine that was stopped and started can come back
# on another host, but the baseline trips and the spread pilot are properties of the pair and do
# not change with a restart. cloud/azure/stage1.sh is pointed at the folder this leaves.
#
# Each campaign is cloud/azure/campaign.sh, which judges every run as it ends and stops itself on
# a stop rule; this stops with it. Everything lands in runs/azure/stage0/<profile>_<start>/, and
# the runs under runs/ as always. The last line of this log is CAMPAIGN_COMPLETE, or STOP_RULE
# with the reason, which is what scripts/testbed_watch.py reads.
. "$(dirname "${BASH_SOURCE[0]}")/../campaigns/common.sh"
set +e
set -o pipefail

KIND="${1:-}"
EARLIER="${2:-}"
# A campaign can only place a trip the calibration reached: the longest step has to cover the
# longest trip the campaign needs, which for A1's 6 ms slice is twice 6 plus a tick. UP_TO_MS in
# the environment says so; the defaults are what stage 0 itself needs.
case "$KIND" in
  first) UP_TO_MS="${UP_TO_MS:-16}"; C0_ROUNDS=4 ;;
  new) UP_TO_MS="${UP_TO_MS:-8}"; C0_ROUNDS=2 ;;
  session) UP_TO_MS="${UP_TO_MS:-8}"; C0_ROUNDS=2 ;;
  *) echo "usage: bash cloud/azure/stage0.sh first|new|session [earlier stage-0 folder with a passing shakedown]"
     exit 2 ;;
esac
PROFILE="${AZ_PROFILE:-unknown}"
LOAD_PCT="${LOAD_PCT:-75}"
# A session that opens a campaign at a reduced core count calibrates at that core count: the
# delay's effect on the trip is measured on the machine as the campaign will run it (A5, D4-6).
CPUS_ARG=()
[ -n "${CPUS:-}" ] && CPUS_ARG=(--cpus "$CPUS")
START="$(date -u +%Y%m%dT%H%M%SZ)"
DIR="runs/azure/stage0/${PROFILE}_$START"
# One seed per design, from the day and the pair, so no two pairs draw the same order.
SEED="${START:0:8}$(printf '%02d' $(( $(printf '%s' "$PROFILE" | cksum | cut -d' ' -f1) % 100 )))"
mkdir -p "$DIR"

log () { echo "$(date -u +%FT%TZ) $*"; }
stop () { log "STOP_RULE: $*"; exit 1; }

design () {  # block label seed [more law_design.py arguments]
  local block="$1" label="$2" seed="$3"
  shift 3
  python3 scripts/law_design.py design --block "$block" --settings "$DIR/settings.json" \
    --seed "$seed" --out "$DIR/$label.json" "$@" | tee -a "$DIR/designs.txt" \
    || stop "the $label design could not be made; see $DIR/designs.txt"
  python3 -c 'import json, sys; sys.exit(0 if json.load(open(sys.argv[1]))["setups"] else 1)' \
    "$DIR/$label.json" || stop "the $label design has no setup this machine can reach"
  python3 scripts/run_queue.py make --design "$DIR/$label.json" --out "$DIR/$label.csv" \
    || stop "the $label queue could not be made"
}

campaign () {  # label [calibration]
  local queue="$DIR/$1.csv" out="$DIR/campaign_$1.log"
  log "== $1: $(python3 scripts/run_queue.py report --queue "$queue" | head -n 1)"
  CALIBRATION="${2:-}" bash cloud/azure/campaign.sh "$queue" 2>&1 | tee "$out"
  if grep -q 'STOP_RULE' "$out"; then
    stop "the $1 campaign stopped itself; see $out"
  fi
  grep -q 'CAMPAIGN_COMPLETE' "$out" || stop "the $1 campaign did not finish; see $out"
}

log "stage 0 on $PROFILE ($KIND pair), writing to $DIR; seeds from $SEED"

if [ -n "$EARLIER" ]; then
  python3 -c 'import json, sys; sys.exit(0 if json.load(open(sys.argv[1]))["ok"] else 1)' \
    "$EARLIER/shakedown.json" 2>/dev/null \
    || stop "$EARLIER holds no passing shakedown to start from"
  cp "$EARLIER/shakedown.json" "$DIR/shakedown_earlier.json"
  echo "$EARLIER" > "$DIR/shakedown_from.txt"
  log "== pilot: the network part only; this pair passed its shakedown in $EARLIER"
  OUT="$DIR/pilot" PARTS=network bash cloud/azure/pilot.sh 2>&1 | tee "$DIR/pilot.log"
  CHECKS="network"
else
  log "== pilot: this pair's shakedown"
  OUT="$DIR/pilot" LOAD_PCT="$LOAD_PCT" bash cloud/azure/pilot.sh 2>&1 | tee "$DIR/pilot.log"
  CHECKS="settings,network,never_negative,load"
fi
python3 scripts/pilot_checks.py shakedown --pilot-dir "$DIR/pilot" --load-pct "$LOAD_PCT" \
  --checks "$CHECKS" > "$DIR/shakedown.json"
case $? in
  0) log "shakedown passed ($CHECKS)" ;;
  1) stop "the shakedown failed; see $DIR/shakedown.json" ;;
  *) stop "the shakedown could not be read; see $DIR/shakedown.json" ;;
esac

sudo python3 scripts/sched_settings.py read > "$DIR/settings.json" \
  || stop "the scheduler settings could not be read"

design C0 "c0_$START" "${SEED}1" --up-to-ms "$UP_TO_MS" --rounds "$C0_ROUNDS" \
  --loads "$LOAD_PCT" "${CPUS_ARG[@]}"
campaign "c0_$START"
C0_QUEUES=(--queue "$DIR/c0_$START.csv")
if [ "$KIND" != first ]; then
  # Two rounds are enough on a quiet pair. On a noisier one the calibration can be too loosely
  # known, and only then, with nothing else wrong, two more rounds run and both stages are fitted.
  python3 scripts/delay_calibration.py fit "${C0_QUEUES[@]}" \
    --out "$DIR/calibration_first_stage.json" 2>&1 | tee "$DIR/fit_first_stage.txt"
  FIRST=$?
  [ "$FIRST" -le 1 ] || stop "the calibration could not be fitted; see $DIR/fit_first_stage.txt"
  if python3 scripts/delay_calibration.py needs-rounds \
      --calibration "$DIR/calibration_first_stage.json"; then
    design C0 "c0b_$START" "${SEED}4" --up-to-ms "$UP_TO_MS" --rounds 2 --first-round 3 \
      --loads "$LOAD_PCT" "${CPUS_ARG[@]}"
    campaign "c0b_$START"
    C0_QUEUES+=(--queue "$DIR/c0b_$START.csv")
  fi
fi

python3 scripts/delay_calibration.py fit "${C0_QUEUES[@]}" \
  --out "$DIR/calibration.json" 2>&1 | tee "$DIR/fit.txt"
FIT=$?
[ "$FIT" -le 1 ] || stop "the calibration could not be fitted; see $DIR/fit.txt"

if [ "$KIND" = session ]; then
  [ "$FIT" = 0 ] || stop "the calibration failed its gate; this session ends and the pair starts a new one. See $DIR/fit.txt"
  log "CAMPAIGN_COMPLETE: the session's calibration passed on $PROFILE; its queues and files are in $DIR"
  exit 0
fi

design B0 "b0_$START" "${SEED}2"
campaign "b0_$START"

[ "$FIT" = 0 ] || stop "the calibration failed its gate, so P0 cannot be placed and this session ends; the pair starts a new one. See $DIR/fit.txt"
design P0 "p0_$START" "${SEED}3" --calibration "$DIR/calibration.json"
campaign "p0_$START" "$DIR/calibration.json"

log "CAMPAIGN_COMPLETE: stage 0 finished on $PROFILE; its queues and files are in $DIR"
