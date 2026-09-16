#!/usr/bin/env bash
# Stage 0 of the frozen experiment plan on one machine pair, from start to end, unattended.
#
# Run on the driver, from the checkout, after cloud/azure/session.sh:
#     nohup bash cloud/azure/stage0.sh first > stage0.log 2>&1 &   # the first x86 pair
#     nohup bash cloud/azure/stage0.sh new > stage0.log 2>&1 &     # the second x86 pair, or Arm
#
# In order, each step only if the ones before it succeeded:
#   1. pilot  cloud/azure/pilot.sh: a new pair's shakedown, or the first pair's retest of its
#             14 September pilot. Its settings, receiver-only delay, load and never-negative
#             checks must pass (scripts/pilot_checks.py shakedown), or nothing else runs.
#   2. C0     the session's delay calibration. On the first pair it is the staircase S0-1: steps
#             up to 16 ms, 4 rounds. On a new pair: up to 8 ms, 2 rounds.
#   3. fit    scripts/delay_calibration.py fit, with its gate.
#   4. B0     the baseline trips. They need no calibration, so they run whatever the gate said.
#   5. P0     the spread pilot, placed from the calibration, and only if its gate passed.
#
# Each campaign is cloud/azure/campaign.sh, which judges every run as it ends and stops itself on
# a stop rule; this stops with it. Everything lands in runs/azure/stage0/<profile>_<start>/, and
# the runs under runs/ as always. The last line of this log is CAMPAIGN_COMPLETE, or STOP_RULE
# with the reason, which is what scripts/testbed_watch.py reads.
. "$(dirname "${BASH_SOURCE[0]}")/../campaigns/common.sh"
set +e
set -o pipefail

KIND="${1:-}"
case "$KIND" in
  first) UP_TO_MS=16; C0_ROUNDS=4 ;;
  new) UP_TO_MS=8; C0_ROUNDS=2 ;;
  *) echo "usage: bash cloud/azure/stage0.sh first|new"; exit 2 ;;
esac
PROFILE="${AZ_PROFILE:-unknown}"
LOAD_PCT="${LOAD_PCT:-75}"
START="$(date -u +%Y%m%dT%H%M%SZ)"
DIR="runs/azure/stage0/${PROFILE}_$START"
# One seed per design, from the day and the pair, so no two pairs draw the same order.
SEED="$(date -u +%Y%m%d)$(printf '%02d' $(( $(printf '%s' "$PROFILE" | cksum | cut -d' ' -f1) % 100 )))"
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

log "== pilot: $([ "$KIND" = first ] && echo "the retest of this pair's first pilot" || echo "this pair's shakedown")"
OUT="$DIR/pilot" LOAD_PCT="$LOAD_PCT" bash cloud/azure/pilot.sh 2>&1 | tee "$DIR/pilot.log"
python3 scripts/pilot_checks.py shakedown --pilot-dir "$DIR/pilot" --load-pct "$LOAD_PCT" \
  > "$DIR/shakedown.json"
case $? in
  0) log "shakedown passed" ;;
  1) stop "the shakedown failed; see $DIR/shakedown.json" ;;
  *) stop "the shakedown could not be read; see $DIR/shakedown.json" ;;
esac

sudo python3 scripts/sched_settings.py read > "$DIR/settings.json" \
  || stop "the scheduler settings could not be read"

design C0 "c0_$START" "${SEED}1" --up-to-ms "$UP_TO_MS" --rounds "$C0_ROUNDS" --loads "$LOAD_PCT"
campaign "c0_$START"

python3 scripts/delay_calibration.py fit --queue "$DIR/c0_$START.csv" \
  --out "$DIR/calibration.json" 2>&1 | tee "$DIR/fit.txt"
FIT=$?
[ "$FIT" -le 1 ] || stop "the calibration could not be fitted; see $DIR/fit.txt"

design B0 "b0_$START" "${SEED}2"
campaign "b0_$START"

[ "$FIT" = 0 ] || stop "the calibration failed its gate, so P0 cannot be placed; see $DIR/fit.txt"
design P0 "p0_$START" "${SEED}3" --calibration "$DIR/calibration.json"
campaign "p0_$START" "$DIR/calibration.json"

log "CAMPAIGN_COMPLETE: stage 0 finished on $PROFILE; its queues and files are in $DIR"
