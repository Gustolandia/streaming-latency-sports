#!/usr/bin/env bash
# One campaign of a main block, in a sitting of its own, from a finished stage 0.
#
# The plan splits the work into small campaigns, each answering one question in one sitting, and
# each of a block's campaigns runs the same number of rounds and shares an anchor slice (D4-1,
# D4-3). This runs one of them:
#
#   1. it takes the machine's settings, the session's delay calibration and the baseline trips
#      from the stage 0 folder it is given, and refuses to run if that calibration did not pass
#      its gate -- the trips are placed from it;
#   2. it writes into the campaign's own log, before the campaign runs, how many rounds it runs
#      and where that number came from (the plan asks for exactly this);
#   3. it makes the design and the shuffled queue, and runs cloud/azure/campaign.sh, which judges
#      every run as it ends and stops itself on a stop rule. This stops with it.
#
# The number of rounds is not worked out here: it comes from scripts/rounds_rule.py, which
# simulates this campaign's own prediction and decision rule at the spread the pair's own spread
# pilot measured, and needs libraries the driver does not carry. Pass it in, with its note.
#
# Everything lands in runs/azure/stage1/<profile>_<start>/, and the runs under runs/ as always.
# The last line of this log is CAMPAIGN_COMPLETE, or STOP_RULE with the reason, which is what
# scripts/testbed_watch.py reads.
#
# Usage:
#   STAGE0=runs/azure/stage0/matched_20260917T231015Z \
#   bash cloud/azure/stage1.sh A1 --slices 3,0.75,1.5 --backend kafka --anchor-slice 3 \
#     --rounds 4 --rounds-note "P1: 4 rounds, from 1000 simulations; seed 20260918"
. "$(dirname "${BASH_SOURCE[0]}")/../campaigns/common.sh"
# Like stage 0 and like every campaign, this carries on past a failing command on purpose: a
# check that fails becomes a STOP_RULE with a reason a person can read, not a silent exit.
set +e
set -o pipefail

BLOCK="${1:-}"
shift
ROUNDS=""
ROUNDS_NOTE=""
DESIGN_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --rounds) ROUNDS="$2"; shift 2 ;;
    --rounds-note) ROUNDS_NOTE="$2"; shift 2 ;;
    *) DESIGN_ARGS+=("$1"); shift ;;
  esac
done

STAGE0="${STAGE0:-}"
if [ -z "$BLOCK" ] || [ -z "$ROUNDS" ] || [ -z "$STAGE0" ]; then
  echo "usage: STAGE0=<stage 0 folder> bash cloud/azure/stage1.sh <block> --rounds <n>" \
       "[--rounds-note <what set it>] [--slices 3,0.75,1.5] [--backend kafka] [--anchor-slice 3]"
  exit 2
fi

PROFILE="${AZ_PROFILE:-unknown}"
START="$(date -u +%Y%m%dT%H%M%SZ)"
DIR="runs/azure/stage1/${PROFILE}_$START"
LABEL="$(printf '%s' "$BLOCK" | tr 'A-Z' 'a-z')_$START"
# One seed per design, from the day and the pair, so no two pairs draw the same order.
SEED="${START:0:8}$(printf '%02d' $(( $(printf '%s' "$PROFILE" | cksum | cut -d' ' -f1) % 100 )))"
mkdir -p "$DIR"

log () { echo "$(date -u +%FT%TZ) $*"; }
stop () { log "STOP_RULE: $*"; exit 1; }

log "stage 1 on $PROFILE: block $BLOCK from $STAGE0, writing to $DIR; seed $SEED"

for f in settings.json calibration.json; do
  [ -s "$STAGE0/$f" ] || stop "$STAGE0 holds no $f; a main campaign is placed from the session's
 calibration and the machine's own settings"
  cp "$STAGE0/$f" "$DIR/$f"
done
[ -s "$STAGE0/baseline.json" ] && cp "$STAGE0/baseline.json" "$DIR/baseline.json"

python3 -c 'import json, sys
fit = json.load(open(sys.argv[1])).get("calibration") or {}
sys.exit(0 if fit and all(at_load.get("gate", {}).get("ok")
                          for backend in fit.values() for at_load in backend.values()) else 1)' \
  "$DIR/calibration.json" \
  || stop "the calibration in $STAGE0 did not pass its gate on every backend, so this campaign
 cannot be placed from it; the pair needs a new session"

# The plan asks for the rounds, and where they came from, in the campaign's log before it runs.
log "rounds: $ROUNDS"
[ -n "$ROUNDS_NOTE" ] && log "rounds from: $ROUNDS_NOTE"
printf '%s\n' "$ROUNDS_NOTE" > "$DIR/rounds_note.txt"

python3 scripts/law_design.py design --block "$BLOCK" --settings "$DIR/settings.json" \
  --calibration "$DIR/calibration.json" --rounds "$ROUNDS" --seed "$SEED" \
  --out "$DIR/$LABEL.json" "${DESIGN_ARGS[@]}" | tee -a "$DIR/designs.txt" \
  || stop "the $LABEL design could not be made; see $DIR/designs.txt"
python3 -c 'import json, sys; sys.exit(0 if json.load(open(sys.argv[1]))["setups"] else 1)' \
  "$DIR/$LABEL.json" || stop "the $LABEL design has no setup this machine can reach"
python3 scripts/run_queue.py make --design "$DIR/$LABEL.json" --out "$DIR/$LABEL.csv" \
  || stop "the $LABEL queue could not be made"

OUT="$DIR/campaign_$LABEL.log"
log "== $LABEL: $(python3 scripts/run_queue.py report --queue "$DIR/$LABEL.csv" | head -n 1)"
CALIBRATION="$DIR/calibration.json" bash cloud/azure/campaign.sh "$DIR/$LABEL.csv" 2>&1 | tee "$OUT"
if grep -q 'STOP_RULE' "$OUT"; then
  stop "the $LABEL campaign stopped itself; see $OUT"
fi
grep -q 'CAMPAIGN_COMPLETE' "$OUT" || stop "the $LABEL campaign did not finish; see $OUT"

log "CAMPAIGN_COMPLETE: $BLOCK on $PROFILE finished; its queue and files are in $DIR"
