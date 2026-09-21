#!/usr/bin/env bash
# Start a campaign as soon as this pair's session calibration passes, on the driver itself.
#
# A pair that finishes its calibration and then waits for someone to notice is a pair billing for
# nothing. Chaining it from a laptop works until the laptop closes: the calibration still
# finishes, the campaign never starts, and the watch deallocates the pair half an hour later
# having learned nothing. This runs on the driver, under nohup, so it survives anything that
# happens to whoever started it.
#
#     nohup bash cloud/azure/chain.sh A3 --rounds 12 --rounds-note "..." > chain.log 2>&1 &
#     nohup bash cloud/azure/chain.sh A3 --rounds-from runs/.../p0_*.csv --backend kafka ... &
#
# --rounds-from names a spread pilot queue; the rounds are then simulated from the plateau, floor
# and spread that pilot measured on this pair (plan version 14, D14-1) once the calibration is
# done and the machine is idle, because a simulation run beside a measurement changes it.
#
# It starts nothing if the calibration fails its gate: a campaign placed from a calibration that
# did not pass is what the gate exists to prevent.
#
# Like stage 0 and every campaign, this carries on past a failing command on purpose: a check
# that fails becomes a STOP_RULE with a reason a person can read, not a silent exit.
. "$(dirname "${BASH_SOURCE[0]}")/../campaigns/common.sh"
set +e
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)" || exit 1

BLOCK="${1:?which block}"
shift
ROUNDS=""
ROUNDS_NOTE=""
ROUNDS_FROM=""
PREDICTION="${PREDICTION:-P3a}"
ARGS=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --rounds) ROUNDS="$2"; shift 2 ;;
    --rounds-note) ROUNDS_NOTE="$2"; shift 2 ;;
    --rounds-from) ROUNDS_FROM="$2"; shift 2 ;;
    *) ARGS+=("$1"); shift ;;
  esac
done

log () { echo "$(date -u +%FT%TZ) $*"; }
stop () { log "STOP_RULE: $*"; exit 1; }

[ -n "$ROUNDS" ] || [ -n "$ROUNDS_FROM" ] \
  || stop "give either --rounds or --rounds-from; a campaign never runs at a number nobody set"

log "chain: waiting for this session's calibration to pass, then $BLOCK"
while true; do
  last=$(tail -1 stage0.log 2>/dev/null)
  case "$last" in
    *"CAMPAIGN_COMPLETE: the session's calibration passed"*) log "the calibration passed"; break ;;
    *STOP_RULE*) stop "the session stopped, so no campaign starts: $last" ;;
  esac
  sleep 120
done

STAGE0=$(ls -d runs/azure/stage0/*_* 2>/dev/null | tail -1)
[ -n "$STAGE0" ] || stop "no stage 0 folder to place a campaign from"
log "chain: stage 0 is $STAGE0"

if [ -n "$ROUNDS_FROM" ]; then
  [ -s "$ROUNDS_FROM" ] || stop "no spread pilot queue at $ROUNDS_FROM"
  log "chain: reading the levels and spread the spread pilot measured on this pair"
  python3 scripts/law_design.py rounds --queue "$ROUNDS_FROM" --block "$BLOCK" \
    --anchor-slice 3 > "$STAGE0/levels_$BLOCK.json" 2>"$STAGE0/levels_$BLOCK.err"
  [ -s "$STAGE0/levels_$BLOCK.json" ] \
    || stop "the levels could not be read; see $STAGE0/levels_$BLOCK.err"
  read -r SPREAD PLATEAU FLOOR <<EOF
$(python3 -c 'import json, sys
one = (json.load(open(sys.argv[1]))["by_backend"] or {}).get(sys.argv[2])
print("%.4f %.4f %.4f" % (one["spread"], one["plateau"], one["floor"]) if one else "")' \
  "$STAGE0/levels_$BLOCK.json" "${BACKEND:-kafka}")
EOF
  [ -n "$SPREAD" ] || stop "the spread pilot gave no levels for ${BACKEND:-kafka}"
  log "chain: ${BACKEND:-kafka} spread $SPREAD, plateau $PLATEAU, floor $FLOOR at the 3 ms anchor"

  python3 scripts/rounds_rule.py for --prediction "$PREDICTION" --loads 50,75,88 --slices 3 \
    --spread "$SPREAD" --plateau "$PLATEAU" --floor "$FLOOR" --seed 20260921 \
    --out "$STAGE0/rounds_$BLOCK.json" > "$STAGE0/rounds_$BLOCK.txt" 2>&1
  ROUNDS=$(python3 -c 'import json, sys
found = json.load(open(sys.argv[1]))
print("" if found.get("broken") else (found.get("rounds") or ""))' \
    "$STAGE0/rounds_$BLOCK.json" 2>/dev/null)
  [ -n "$ROUNDS" ] \
    || stop "the rounds rule gave no number for $PREDICTION; see $STAGE0/rounds_$BLOCK.txt"
  SHARE=$(python3 -c 'import json, sys
found = json.load(open(sys.argv[1]))
at = [s for s in found["tried"] if s["rounds"] == found["rounds"]]
print("%.0f%% under the law and %.0f%% where it is false"
      % (100 * at[0]["power"], 100 * at[0]["false_confirm"]) if at else "an unrecorded share")' \
    "$STAGE0/rounds_$BLOCK.json" 2>/dev/null)
  ROUNDS_NOTE="$PREDICTION: $ROUNDS rounds, confirmed in $SHARE of 1000 simulated campaigns, at the plateau and floor the spread pilot measured on this pair ($PLATEAU and $FLOOR at the 3 ms anchor, plan version 14 D14-1) and at its ${BACKEND:-kafka} spread ($SPREAD); seed 20260921"
fi

log "chain: $BLOCK at $ROUNDS rounds"
log "chain: rounds from: $ROUNDS_NOTE"
rm -f stage1.log
STAGE0="$STAGE0" bash cloud/azure/stage1.sh "$BLOCK" --rounds "$ROUNDS" \
  --rounds-note "$ROUNDS_NOTE" "${ARGS[@]}" > stage1.log 2>&1
log "chain: stage 1 finished; see stage1.log"
