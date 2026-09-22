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
BACKENDS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --rounds) ROUNDS="$2"; shift 2 ;;
    --rounds-note) ROUNDS_NOTE="$2"; shift 2 ;;
    # Taken here as well as passed on: the campaign is placed from this backend's calibration and
    # from no other, so it is this backend's gate that has to have passed.
    --backend) BACKENDS+=("$2"); DESIGN_ARGS+=("$1" "$2"); shift 2 ;;
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

# A calibration is a property of the machine it was measured on. Stage 0 says so itself: a pair
# that was stopped and started needs its own calibration for the session ahead, because it can
# come back on another host. So a campaign is placed only from one measured on this boot.
#
# On 21 September A8 was placed from a calibration fitted at 22:28 on a pair that booted again at
# 00:48, and the got-it brake stopped it three runs in. The brake was right -- the instrument had
# moved under it -- but nothing had said that placing the campaign was the mistake.
BOOTED=$(date -u -d "$(uptime -s)" +%s 2>/dev/null || echo 0)
FITTED=$(date -u -r "$STAGE0/calibration.json" +%s 2>/dev/null || echo 0)
if [ "$BOOTED" != 0 ] && [ "$FITTED" != 0 ] && [ "$FITTED" -lt "$BOOTED" ]; then
  stop "the calibration in $STAGE0 was fitted at $(date -u -d "@$FITTED" +%FT%TZ), before this
 machine last booted at $(date -u -d "@$BOOTED" +%FT%TZ). A pair that was stopped and started
 needs a new session: bash cloud/azure/stage0.sh session $STAGE0"
fi

# A session that opens A8 fits one calibration per client, so the gates sit one level deeper
# (client, then backend, then load) than in every other session. Walk down to whatever carries a
# gate rather than counting levels, keeping the names on the way so a gate can be told which
# backend it belongs to.
#
# Only the backends this campaign runs have to have passed. It used to require every gate in the
# file, and that cost this plan three sessions on 22 September: on the second x86 pair Kafka's
# calibration cannot be known within 0.3 ms on the coarse-tick kernels -- 0.311 to 0.410 against
# the 0.3 the gate asks -- while Redis's is 0.128 to 0.237 on every kernel. Redis campaigns were
# refused for the state of a calibration they are not placed from. A campaign is placed from its
# own backend's fit and from no other; that is what has to be sound.
python3 -c 'import json, sys
def gates(node, path=()):
    if isinstance(node, dict):
        if "gate" in node:
            yield path, bool(node["gate"].get("ok"))
            return
        for name, below in node.items():
            for found in gates(below, path + (name,)):
                yield found
fit = json.load(open(sys.argv[1])).get("calibration") or {}
wanted = set(sys.argv[2:])
found = list(gates(fit))
if wanted:
    found = [(path, ok) for path, ok in found if set(path) & wanted]
sys.exit(0 if found and all(ok for _, ok in found) else 1)' \
  "$DIR/calibration.json" "${BACKENDS[@]}" \
  || stop "the calibration in $STAGE0 did not pass its gate for ${BACKENDS[*]:-every backend}, so
 this campaign cannot be placed from it; the pair needs a new session"

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

# Before anything runs: which of these runs the got-it brake can judge and which it cannot.
# A8 takes its note two ways and a calibration takes it one way, so half its runs have no
# like-for-like baseline and are recorded rather than braked (plan version 16, D16-1). Saying so
# here is the difference between knowing it now and finding it on the third run, hours in.
python3 - "$DIR/$LABEL.csv" > "$DIR/gotit_brake.txt" 2>&1 <<'PY'
import collections, json, sys
sys.path.insert(0, "scripts")
import run_integrity, run_queue
rows = run_queue.read_queue(sys.argv[1])
counted = collections.Counter()
for row in rows:
    params = json.loads(row["params"])
    counted[(params.get("ack_stamp") or run_integrity.CALIBRATED_AT,
             run_integrity.gotit_comparable(params))] += 1
for (where, judged), many in sorted(counted.items()):
    print("got-it note taken %-9s %4d run(s): %s"
          % (where, many,
             "held against this campaign's own earlier runs of the same setup"
             " (the first two of each are recorded, not braked)" if judged
             else "no like-for-like baseline, so recorded and not braked"))
PY
sed 's/^/   /' "$DIR/gotit_brake.txt"

OUT="$DIR/campaign_$LABEL.log"
log "== $LABEL: $(python3 scripts/run_queue.py report --queue "$DIR/$LABEL.csv" | head -n 1)"
CALIBRATION="$DIR/calibration.json" bash cloud/azure/campaign.sh "$DIR/$LABEL.csv" 2>&1 | tee "$OUT"
if grep -q 'STOP_RULE' "$OUT"; then
  stop "the $LABEL campaign stopped itself; see $OUT"
fi
grep -q 'CAMPAIGN_COMPLETE' "$OUT" || stop "the $LABEL campaign did not finish; see $OUT"

log "CAMPAIGN_COMPLETE: $BLOCK on $PROFILE finished; its queue and files are in $DIR"
