#!/usr/bin/env bash
# One of A2's tick sessions, from a cold driver to a running campaign.
#
# A2 is twelve sessions of one kernel and one backend each, plus two bridge sessions on the stock
# kernel (D4-7). Every one of them needs the same six steps, and the tick is fixed at boot, so
# every one of them needs a reboot in the middle. That is the part no campaign script can do for
# itself: the driver reboots, so whatever is driving has to be somewhere else. This runs from the
# machine that holds the hosts file, as session.sh does.
#
#     HOSTS_ENV=cloud/hosts_b.env bash cloud/azure/a2_session.sh 1000 kafka
#     HOSTS_ENV=cloud/hosts_b.env bash cloud/azure/a2_session.sh stock redis    # a bridge session
#
# It starts the campaign and returns; the campaign itself runs on the driver under nohup and
# survives whatever happens to whoever started it. Watch it with runs/azure_watch, or by reading
# stage0.log and chain.log on the driver.
#
# The steps, and why each is here rather than assumed:
#
#   1. the pair is running            a pair the watch deallocated is started again
#   2. the kernel is booted           kernels.sh boot, then a reboot, then kernels.sh check --
#                                     the check is the thing that says the tick is real
#   3. the session is rebuilt         a reboot takes the receiver's namespace and the brokers
#                                     with it, so session.sh runs after every boot
#   4. the calibration is measured    on this boot, because stage1 refuses one fitted before it
#   5. the campaign is chained        chain.sh waits for the calibration's gate and starts A2
#
# Strict, like session.sh, the other half of this kit that runs where the hosts file is rather
# than on the driver. The campaign scripts carry on past failures on purpose because a campaign
# must report a reason rather than vanish; this one has nothing to report to, so it stops. The
# three commands that are *expected* to fail say so where they are.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)" || exit 1

HZ="${1:?which tick: 1000, 250, 100, or stock for a bridge session}"
BACKEND="${2:?which backend: kafka or redis}"
HOSTS_ENV="${HOSTS_ENV:-cloud/hosts.env}"
ROUNDS="${ROUNDS:-4}"
#: Rounds of the session's own calibration. Two is enough on the two faster kernels; the
#: HZ=100 one needed four, its Kafka fit having come back known within 0.387 ms against a
#: 0.3 gate while Redis on the same boot passed at 0.198.
C0_ROUNDS="${C0_ROUNDS:-2}"
ROUNDS_NOTE="${ROUNDS_NOTE:-D14-5: the rounds rule simulates one tick at a time and P2, P2b and P2c compare two kernels, so it cannot set a number for A2; the plan runs it at its floor of 4 rounds with the power unknown.}"

log () { echo "$(date -u +%FT%TZ) $*"; }
stop () { log "STOP_RULE: $*"; exit 1; }

case "$BACKEND" in kafka|redis) ;; *) stop "backend must be kafka or redis, not $BACKEND" ;; esac
case "$HZ" in 1000|250|100|stock) ;; *) stop "tick must be 1000, 250, 100 or stock, not $HZ" ;; esac

[ -r "$HOSTS_ENV" ] || stop "no $HOSTS_ENV; name one with HOSTS_ENV="
# shellcheck disable=SC1090
. "$HOSTS_ENV"
: "${DRIVER_PUBLIC:?$HOSTS_ENV has no DRIVER_PUBLIC}"
: "${SSH_KEY:?$HOSTS_ENV has no SSH_KEY}"
OPTS=(-i "$SSH_KEY" -o StrictHostKeyChecking=no -o BatchMode=yes -o ConnectTimeout=20)
drv () { ssh "${OPTS[@]}" "ubuntu@$DRIVER_PUBLIC" "$@"; }

#: How far the session's calibration has to reach.
#:
#: A2's longest point is f2sh, a trip of twice the slice plus twice the tick, and its longest
#: slice is 3 ms. At HZ=1000 that is 8 ms; at 250 it is 14; at 100 it is 26. A campaign cannot
#: place a trip its calibration never reached, and the calibration's steps double, so this is the
#: first power of two at or above the longest trip. Getting it wrong does not fail loudly -- the
#: design quietly drops the setups it cannot reach -- which is why it is computed rather than
#: typed.
#: Plain shell arithmetic, and no python3: this half runs on whatever holds the hosts file, and
#: on Windows that is a git-bash with no python3 on its path. A helper that works on the driver
#: and not on the machine driving it is the kind of thing that only shows up on the day it runs.
reach_ms () {
  local hz="$1" tick longest up
  [ "$hz" = stock ] && hz=1000
  tick=$(( 1000 / hz ))               # 1, 4 and 10 ms; the three ticks divide exactly
  longest=$(( 2 * 3 + 2 * tick ))     # f2sh at A2's longest slice, 3 ms
  up=8
  while [ "$up" -lt "$longest" ]; do up=$(( up * 2 )); done
  echo "$up"
}

UP_TO_MS="${UP_TO_MS:-$(reach_ms "$HZ")}"

log "A2 session: tick $HZ, backend $BACKEND, $ROUNDS rounds, calibration reaching $UP_TO_MS ms"

log "== 1/5 the pair is running"
if ! drv true 2>/dev/null; then
  # The watch deallocates a pair that has been idle for half an hour, which is most of the gap
  # between one A2 session and the next, so this is the ordinary case and not an error.
  command -v az >/dev/null || stop "the driver is not answering and az is not here to start it"
  : "${DRIVER_NAME:?$HOSTS_ENV has no DRIVER_NAME, so the pair cannot be found to start}"
  # Asked for, not derived. The group is sbl-azb for a driver called sbl-azb-drv but sbl-azarm
  # for one called sbl-az-arm-drv, so stripping the suffix is right twice and wrong once.
  group=$(az vm list --query "[?name=='$DRIVER_NAME'].resourceGroup | [0]" -o tsv 2>/dev/null)
  [ -n "$group" ] || stop "azure does not list a VM called $DRIVER_NAME, so its pair cannot be started"
  log "   the driver is not answering; starting every machine in $group"
  names=$(az vm list -g "$group" --query "[].name" -o tsv 2>/dev/null)
  [ -n "$names" ] || stop "the group $group holds no machines to start"
  # One at a time, by name. `az vm start --ids a b` accepted a list of ids and started the
  # driver alone, so the broker stayed deallocated, session.sh could not reach it, and the
  # session stopped three steps later with the machine looking fine.
  for machine in $names; do
    az vm start --resource-group "$group" --name "$machine" --no-wait >/dev/null 2>&1 || true
    log "   asked $machine to start"
  done
  for _ in $(seq 1 40); do drv true 2>/dev/null && break; sleep 15; done
  drv true 2>/dev/null || stop "the driver did not come back after its pair was started"
fi
log "   driver is up on $(drv 'uname -r')"

log "== 2/5 the kernel"
if [ "$HZ" = stock ]; then
  # A bridge session runs on the kernel a plain restart gives, which kernels.sh pins to the
  # stock one. Rebooting is still the way to get there, because the session before this one
  # left the machine on a tick build.
  # A reboot cuts the connection that asked for it, so ssh returns non-zero on success.
  drv 'cd sbl && sudo systemctl reboot' >/dev/null 2>&1 || true
else
  drv "cd sbl && git pull -q origin main && bash cloud/azure/kernels.sh boot $HZ" || stop "the HZ=$HZ kernel could not be readied"
  # Same here: the reboot kills its own ssh.
  drv 'sudo systemctl reboot' >/dev/null 2>&1 || true
fi
sleep 20
for _ in $(seq 1 40); do drv true 2>/dev/null && break; sleep 10; done
drv true 2>/dev/null || stop "the driver did not come back from its reboot"
running=$(drv 'uname -r')
log "   booted $running"
if [ "$HZ" = stock ]; then
  case "$running" in *sbl*) stop "a bridge session must run on the stock kernel, and this is $running" ;; esac
else
  case "$running" in *"sbl$HZ") ;; *) stop "asked for HZ=$HZ and the machine came up on $running" ;; esac
  drv "cd sbl && bash cloud/azure/kernels.sh check $HZ" || stop "HZ=$HZ did not pass its checks, so no campaign runs on it"
fi

log "== 3/5 the session, which the reboot took with it"
HOSTS_ENV="$HOSTS_ENV" bash cloud/azure/session.sh > /dev/null 2>&1 || stop "session.sh did not finish; run it by hand and read what it says"
log "   brokers and the receiver's namespace are back"

log "== 4/5 the calibration, measured on this boot"
earlier=$(drv 'cd sbl && for d in runs/azure/stage0/*_*; do [ -s "$d/shakedown.json" ] || continue; python3 -c "import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get(\"ok\") else 1)" "$d/shakedown.json" 2>/dev/null && echo "$d"; done | tail -1' || true)
[ -n "$earlier" ] || stop "this pair has no stage 0 folder with a passing shakedown to start a session from"
log "   starting from the shakedown in $earlier"
drv "cd sbl; UP_TO_MS=$UP_TO_MS LOAD_PCT=75 C0_ROUNDS=$C0_ROUNDS setsid nohup bash cloud/azure/stage0.sh session $earlier > stage0.log 2>&1 < /dev/null &" >/dev/null 2>&1
sleep 15
drv 'cd sbl && head -1 stage0.log' | grep -q "stage 0 on" || stop "the session calibration did not start; read stage0.log on the driver"

log "== 5/5 the campaign, waiting on that calibration's gate"
drv "cd sbl; setsid nohup bash cloud/azure/chain.sh A2 --rounds $ROUNDS --rounds-note \"$ROUNDS_NOTE\" --backend $BACKEND --anchor-slice 3 > chain.log 2>&1 < /dev/null &" >/dev/null 2>&1
sleep 10
drv 'cd sbl && head -1 chain.log' | grep -q "chain:" || stop "the chain did not start; read chain.log on the driver"

log "CAMPAIGN_COMPLETE: A2 at tick $HZ on $BACKEND is chained behind its calibration"
log "  watch it:  ssh ... 'cd sbl && tail -f chain.log'   (stage0.log until the calibration passes)"
