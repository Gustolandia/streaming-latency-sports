#!/usr/bin/env bash
# E-X3: how many samples does the OpenMessaging Benchmark discard, AS A FUNCTION OF LOAD?
#
# Referee round 2, M3. The existing evidence that the exposure is not ours alone is a single
# three-minute run at 88% load: 6,000 samples discarded, one cell, one broker, no replication.
# That is an existence proof. It answers "can this happen to someone else" and not "when".
#
# This sweeps the load axis with replication. The deliverable is a curve, not a number, and the
# prediction is specific enough to fail: if inversions come from scheduling stalls outlasting the
# measured interval, OMB's discard count should be near zero on an idle machine and climb with
# load, in the same direction and roughly the same shape as our own inversion rate does.
#
#   discards ~ 0 at 0% and rising with load   -> the mechanism transfers to a harness we did not
#                                                write, and the 6,000 was not a one-off cell
#   flat across load                          -> the discards have some other cause and our
#                                                account of THEM is wrong, whatever our own
#                                                measurements show
#   non-monotone or noisy beyond the reps     -> report as such; three points make a direction,
#                                                not a law
#
# Each cell is a separate invocation of omb_discard_count.sh with its own OUT, so a cell that
# fails its publish-output guard leaves the others intact and is visible as a gap rather than as
# a zero. That guard exists because an earlier version of this campaign reported a zero from a
# run that had died four seconds in, and the zero reached the manuscript.
#
# Usage:
#   nohup bash cloud/campaigns/omb_load_sweep.sh > omb_sweep.log 2>&1 &
#   LEVELS="0 88" REPS=1 bash cloud/campaigns/omb_load_sweep.sh     # short smoke run
set -u

cd ~/sbl || exit 1

LEVELS="${LEVELS:-0 50 75 88 95}"
REPS="${REPS:-3}"
DURATION_MIN="${DURATION_MIN:-3}"
SWEEP_OUT="${SWEEP_OUT:-docs/results/external/load_sweep}"
COMBINED="$SWEEP_OUT/omb_load_sweep.csv"

# omb_discard_count.sh builds its payload path as "$PWD/$OUT", so an absolute OUT yields
# ~/sbl//tmp/... and the run dies at the payload step. Caught by the first smoke test; rejected
# here with the reason rather than left to fail three cells in.
case "$SWEEP_OUT" in
  /*) echo "FATAL: SWEEP_OUT must be relative to ~/sbl (got '$SWEEP_OUT')"; exit 1 ;;
esac

mkdir -p "$SWEEP_OUT"
printf 'load_pct,rep,valid,discarded_total,discarded_zero,discarded_negative,most_negative_micros,kept,pub_lines\n' > "$COMBINED"

echo "=== OMB load sweep starting $(date -u +%FT%TZ) ==="
echo "    levels: $LEVELS   reps: $REPS   duration: ${DURATION_MIN}min per cell"

wait_clear () {
  # Never start a cell while another CPU consumer is running: the load level IS the
  # independent variable here, so a stray campaign in the background silently changes it.
  while pgrep -f 'run_concurrency_test\.py' >/dev/null \
     || pgrep -x stress-ng >/dev/null \
     || pgrep -f 'load_geometry\.sh|ttrue_sweep\.sh|stall_distribution\.sh' >/dev/null; do
    sleep 30
  done
  sleep 10
}

for L in $LEVELS; do
  for R in $(seq 1 "$REPS"); do
    CELL="$SWEEP_OUT/l${L}_rep${R}"
    echo "--- load ${L}% rep ${R}  $(date -u +%FT%TZ) ---"
    wait_clear
    mkdir -p "$CELL"

    LOAD_PCT="$L" OUT="$CELL" DURATION_MIN="$DURATION_MIN" \
      timeout -k 60 1800 bash cloud/campaigns/omb_discard_count.sh 2>&1 | tail -6
    rc=${PIPESTATUS[0]}

    RES="$CELL/omb_loaded_result.csv"
    if [ "$rc" != "0" ] || [ ! -s "$RES" ]; then
      echo "CELL FAILED load=${L}% rep=${R} rc=$rc -- no row written"
      continue
    fi

    # Take the data row from the cell's own CSV rather than re-deriving it here: the
    # campaign already applied its validity guard, and duplicating that logic is how the
    # two copies drift apart.
    python3 - "$RES" "$L" "$R" "$COMBINED" <<'PY'
import csv, sys
res, load, rep, combined = sys.argv[1:5]
with open(res, newline="", encoding="utf-8") as fh:
    rows = list(csv.DictReader(fh))
if not rows:
    sys.exit(0)
r = rows[0]
with open(combined, "a", newline="", encoding="utf-8") as fh:
    csv.writer(fh).writerow([load, rep, r.get("valid", ""),
                             r.get("discarded_total", ""), r.get("discarded_zero", ""),
                             r.get("discarded_negative", ""),
                             r.get("most_negative_micros", ""), r.get("kept", ""),
                             r.get("pub_lines", "")])
PY
    echo "recorded: $(tail -1 "$COMBINED")"
  done
done

echo
echo "=== sweep complete $(date -u +%FT%TZ) ==="
cat "$COMBINED"
echo "=== OMB_LOAD_SWEEP_COMPLETE ==="
