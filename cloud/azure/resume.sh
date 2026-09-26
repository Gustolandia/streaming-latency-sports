#!/usr/bin/env bash
# Finish a campaign that stopped before its runs were all done: from its own queue, under the same
# calibration its first runs had, on the kernel they ran on, with the got-it brake recording rather
# than stopping (plan version 32, D32-2). What A5's two-CPU campaign did on 25 September (D26-1),
# made general.
#
#     bash cloud/azure/resume.sh runs/azure/stage1/<campaign folder>
#
# Run by the pair's own queue as a command job with boot=none, after the job before it, so the
# receiver's namespace is in place; the brokers are put back here, as the queue does before a
# block job. The runs it adds go on the campaign's own queue and are that campaign's runs: its log
# gains a line saying where the resumed part begins, and a run that was interrupted is recorded
# as failed and run again, as campaign.sh always does. It does nothing to a finished campaign.
. "$HOME/sbl/cloud/campaigns/common.sh"
#: As every campaign script here: carry on past a failing command so its failure is reported.
set +e
cd "$HOME/sbl" || exit 1
log () { echo "$(date -u +%FT%TZ) resume: $*"; }

DIR="${1:?which campaign folder}"
DIR="${DIR%/}"
QUEUE_CSV=$(ls "$DIR"/*_20*.csv 2>/dev/null | head -n 1)
MAIN_LOG=$(ls "$DIR"/campaign_*.log 2>/dev/null | head -n 1)
SSH_OPTS=(-i "$SSH_KEY" -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=20)

[ -f "$QUEUE_CSV" ] && [ -f "$MAIN_LOG" ] || { log "no queue or log in $DIR"; exit 2; }
[ -s "$DIR/calibration.json" ] || { log "no calibration in $DIR; not resuming"; exit 2; }
[ -e runs/azure/STOP ] && { log "runs/azure/STOP is present; not resuming"; exit 2; }
grep -q "GOTIT_BRAKE" cloud/azure/campaign.sh || { log "this checkout has no recording brake"; exit 2; }
ran_on=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get("release") or "")' \
  "$DIR/settings.json" 2>/dev/null)
[ -n "$ran_on" ] || { log "$DIR/settings.json does not say which kernel it ran on; not resuming"; exit 2; }
[ "$ran_on" = "$(uname -r)" ] \
  || { log "it ran on $ran_on and this is $(uname -r); a campaign is finished on its own kernel"; exit 2; }
left=$(python3 -c 'import csv, sys
print(sum(1 for r in csv.DictReader(open(sys.argv[1])) if r["status"] in ("queued", "running")))' \
  "$QUEUE_CSV")
[ "${left:-0}" -gt 0 ] || { log "nothing left to run in $QUEUE_CSV"; exit 0; }
log "$left runs left in $QUEUE_CSV, on $(uname -r) with $(nproc) CPUs; code $(git rev-parse --short HEAD)"
log "the queue before: $(python3 scripts/run_queue.py report --queue "$QUEUE_CSV" | head -n 1)"

log "putting the brokers back, as the queue does before a block job"
ssh "${SSH_OPTS[@]}" "ubuntu@$BROKER_PRIV" "cd sbl && sudo python3 scripts/receiver_delay.py broker-clear --apply >/dev/null && sudo bash cloud/brokers.sh $BROKER_PRIV" >/dev/null 2>&1 \
  || { log "the brokers did not come back"; exit 2; }
sudo ip netns list 2>/dev/null | grep -qw sblrecv || { log "the receiver's namespace is missing"; exit 2; }

{
  echo "=== $(date -u +%FT%TZ) resumed from its own queue with the got-it brake recording (D32-2); same calibration, same kernel"
  GOTIT_BRAKE=record CALIBRATION="$DIR/calibration.json" bash cloud/azure/campaign.sh "$QUEUE_CSV"
} 2>&1 | tee "${MAIN_LOG%.log}.resumed.log" >> "$MAIN_LOG"

log "the queue after: $(python3 scripts/run_queue.py report --queue "$QUEUE_CSV" | head -n 1)"
if grep -q STOP_RULE "${MAIN_LOG%.log}.resumed.log"; then
  log "STOPPED again, on a rule the recording brake does not cover: $(grep STOP_RULE "${MAIN_LOG%.log}.resumed.log" | tail -n 1 | cut -c22-)"
  exit 3
fi
grep -q CAMPAIGN_COMPLETE "${MAIN_LOG%.log}.resumed.log" || { log "it ended without finishing"; exit 4; }
log "COMPLETE: $DIR has all its runs"
exit 0
