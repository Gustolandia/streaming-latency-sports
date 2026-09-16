#!/usr/bin/env bash
# Start a working session on the Azure testbed, from your own computer.
#
# Run it once the machines exist (scripts/azure_testbed.py up, then hosts --write
# cloud/hosts.env), and again after every start that follows a stop. Deallocating a machine is a
# reboot: the receiver's namespace, the broker containers and any hand-set slice do not survive
# it, and this puts them back.
#
# Every step is safe to repeat:
#   1. the commit you are on must already be on GitHub, because the machines fetch it from there;
#   2. wait until cloud-init has finished on both machines;
#   3. switch automatic package upgrades off on both, and wait for any upgrade already running.
#      On 16 September one restarted the driver's network service in the middle of a pilot, and
#      the driver lost its broker. Nothing may change the software under a campaign either;
#   4. bring both checkouts to that commit;
#   5. give the driver the testbed key and hosts.env (the campaigns SSH from the driver to the
#      broker, as they did on Oracle);
#   6. start Kafka and Redis on the broker (cloud/brokers.sh), with no delay on its card;
#   7. build the receiver's namespace on the driver (scripts/receiver_delay.py driver), which also
#      takes the receiver's address out of netplan's settings so that no restart brings it back;
#   8. read the scheduler settings on both machines into runs/azure_settings/.
#
# Usage:  bash cloud/azure/session.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
HOSTS_ENV="${HOSTS_ENV:-$ROOT/cloud/hosts.env}"
[ -f "$HOSTS_ENV" ] || {
  echo "FATAL: no $HOSTS_ENV; run: python scripts/azure_testbed.py hosts --write cloud/hosts.env"
  exit 1
}
# shellcheck disable=SC1090
. "$HOSTS_ENV"
: "${DRIVER_PUBLIC:?hosts.env has no DRIVER_PUBLIC; write it with scripts/azure_testbed.py hosts}"
KEY="${LOCAL_SSH_KEY:-$HOME/.ssh/azure_sbl}"
COMMIT="$(git -C "$ROOT" rev-parse HEAD)"
OPTS=(-i "$KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30)

drv () { ssh "${OPTS[@]}" "ubuntu@$DRIVER_PUBLIC" "$@"; }
brk () {
  ssh "${OPTS[@]}" -o "ProxyCommand=ssh ${OPTS[*]} -W %h:%p ubuntu@$DRIVER_PUBLIC" \
      "ubuntu@$BROKER_PRIV" "$@"
}

echo "== 1/8 is $COMMIT on GitHub?"
git -C "$ROOT" fetch --quiet origin
if [ -z "$(git -C "$ROOT" branch -r --contains "$COMMIT")" ]; then
  echo "FATAL: $COMMIT is not on GitHub yet. Push it first: the machines fetch it from there."
  exit 1
fi
if [ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]; then
  echo "WARNING: uncommitted changes stay on this computer; the machines run $COMMIT as pushed."
fi

echo "== 2/8 waiting for cloud-init on both machines"
drv 'cloud-init status --wait >/dev/null; test -f /var/lib/sbl-cloud-init-done' || {
  echo "FATAL: the driver's setup did not finish; see /var/log/cloud-init-output.log there"
  exit 1
}
brk 'cloud-init status --wait >/dev/null; test -f /var/lib/sbl-cloud-init-done' || {
  echo "FATAL: the broker's setup did not finish; see /var/log/cloud-init-output.log there"
  exit 1
}

echo "== 3/8 automatic package upgrades off on both machines, and any running one finished"
for host in drv brk; do
  "$host" 'sudo systemctl disable --now unattended-upgrades.service apt-daily.timer apt-daily-upgrade.timer >/dev/null 2>&1; printf "APT::Periodic::Update-Package-Lists \"0\";\nAPT::Periodic::Unattended-Upgrade \"0\";\n" | sudo tee /etc/apt/apt.conf.d/20auto-upgrades >/dev/null && timeout 1800 bash -c "while sudo fuser /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock >/dev/null 2>&1; do sleep 5; done"'
done

echo "== 4/8 both checkouts to $COMMIT"
for host in drv brk; do
  "$host" "cd sbl && git fetch --quiet --depth 1 origin $COMMIT \
    && git checkout --quiet --detach $COMMIT && git log -1 --format='  %h %s'"
done

echo "== 5/8 testbed key and hosts.env to the driver"
scp "${OPTS[@]}" "$KEY" "ubuntu@$DRIVER_PUBLIC:.ssh/azure_sbl"
drv 'chmod 600 ~/.ssh/azure_sbl'
scp "${OPTS[@]}" "$HOSTS_ENV" "ubuntu@$DRIVER_PUBLIC:sbl/cloud/hosts.env"

echo "== 6/8 Kafka and Redis on the broker, no delay on its card"
brk "cd sbl && sudo python3 scripts/receiver_delay.py broker-clear --apply >/dev/null \
  && sudo bash cloud/brokers.sh $BROKER_PRIV"

echo "== 7/8 the receiver's namespace on the driver"
drv "cd sbl && sudo python3 scripts/receiver_delay.py driver \
  --address $RECEIVER_IP/$SUBNET_PREFIX --gateway $SUBNET_GATEWAY --apply"

echo "== 8/8 scheduler settings"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$ROOT/runs/azure_settings"
drv "cd sbl && sudo python3 scripts/sched_settings.py read" \
  > "$ROOT/runs/azure_settings/${AZ_PROFILE}_driver_$STAMP.json"
brk "cd sbl && sudo python3 scripts/sched_settings.py read" \
  > "$ROOT/runs/azure_settings/${AZ_PROFILE}_broker_$STAMP.json"

echo "session ready. On the driver:  ssh -i $KEY ubuntu@$DRIVER_PUBLIC  then  cd sbl"
