#!/usr/bin/env bash
# The matched replication: the Oracle mechanism campaigns, unchanged, on an Azure driver.
#
# Every mechanism result so far came from one Oracle machine type and one kernel, and a referee
# asked for the load-geometry contrast and the payload sweep on a materially different machine.
# This runs those two, and the go-first test, with the campaign scripts exactly as they ran on
# Oracle. On profile "matched" only the provider changes; on profile "arm" the machine changes
# too. The receiver-only delay is not used here, because it did not exist on Oracle.
#
# Run on the driver after cloud/azure/session.sh and a passing pilot:
#     nohup bash cloud/azure/replicate_oracle.sh > replicate.log 2>&1 &
#
# The campaigns run in an order shuffled from REPLICATION_SEED, which the log prints. Each writes
# to its own time-stamped directory, with the scheduler settings read before and after it.
. "$(dirname "${BASH_SOURCE[0]}")/../campaigns/common.sh"
set +e

: "${AZ_PROFILE:?hosts.env has no AZ_PROFILE; is this the Azure testbed?}"
BASE="${BASE:-runs/azure/replication/$AZ_PROFILE}"
CAMPAIGNS="${CAMPAIGNS:-stamping_priority load_geometry ttrue_sweep}"
SEED="${REPLICATION_SEED:-$(date -u +%Y%m%d)}"
mkdir -p "$BASE"
remote_broker "cd sbl && sudo python3 scripts/receiver_delay.py broker-clear --apply" \
  >/dev/null 2>&1

# shellcheck disable=SC2086
ORDER=$(python3 -c 'import random, sys
names = sys.argv[2:]
random.Random(int(sys.argv[1])).shuffle(names)
print(" ".join(names))' "$SEED" $CAMPAIGNS)
banner "replication on $AZ_PROFILE, seed $SEED, order: $ORDER"

for C in $ORDER; do
  DIR="$BASE/${C}_$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "$DIR"
  sudo python3 scripts/sched_settings.py read > "$DIR/settings_before.json"
  banner "$C -> $DIR"
  OUT="$DIR" bash "cloud/campaigns/$C.sh" > "$DIR/campaign.log" 2>&1
  echo "  $C exited with $?"
  sudo python3 scripts/sched_settings.py read > "$DIR/settings_after.json"
done

banner "REPLICATION_COMPLETE"
