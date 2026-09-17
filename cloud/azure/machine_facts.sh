#!/usr/bin/env bash
# What a machine is, as far as its network and timing go: printed, to be kept with a pilot.
#
# Run from the checkout, on the driver or on the broker (the pilot runs it on both):
#     bash cloud/azure/machine_facts.sh > facts.txt
#
# On 16 and 17 September the two x86 pairs' paths differed in ways no file recorded: a start
# after a stop can put a machine on another physical host, and nothing said which card, driver,
# queues or interrupt settings a session had. Every line is allowed to fail: a fact that cannot
# be read is written down as such, and the pilot carries on.
set -euo pipefail

section () { echo "== $*"; }
try () { "$@" 2>&1 || echo "(failed: $*)"; }

section date; try date -u
section uname; try uname -a
section boot; try uptime; try awk '/^btime/ {print $2}' /proc/stat
section cmdline; try cat /proc/cmdline
section kernel config
try grep -E "^CONFIG_(HZ|NO_HZ|HIGH_RES_TIMERS|PREEMPT|CPU_IDLE|SCHED_HRTICK)" "/boot/config-$(uname -r)"
section clocksource
try cat /sys/devices/system/clocksource/clocksource0/current_clocksource \
  /sys/devices/system/clocksource/clocksource0/available_clocksource
section cpuidle
try cat /sys/devices/system/cpu/cpuidle/current_driver /sys/devices/system/cpu/cpuidle/current_governor
section lscpu; try lscpu
section dmi
try cat /sys/class/dmi/id/product_name /sys/class/dmi/id/product_version /sys/class/dmi/id/bios_version
section modules; try bash -c 'lsmod | grep -Ei "mana|netvsc|hv_|mlx|ipvlan"'
section links; try ip -d link show
section addresses; try ip -o addr show
section routes; try ip route show
section neighbours; try ip neigh show
for dev in /sys/class/net/*; do
  dev="${dev##*/}"
  [ "$dev" = lo ] && continue
  section "ethtool $dev"
  try ethtool -i "$dev"
  try ethtool -k "$dev"
  try ethtool -c "$dev"
  try ethtool -l "$dev"
  section "queues $dev"
  for q in /sys/class/net/"$dev"/queues/*; do
    echo "$q rps=$(cat "$q/rps_cpus" 2>/dev/null) xps=$(cat "$q/xps_cpus" 2>/dev/null)"
  done
done
section interrupts; try bash -c 'grep -Ei "mana|hv|eth|mlx|CPU" /proc/interrupts | head -40'
section qdisc; try tc -s qdisc show
section tcp; try bash -c 'grep -E "^Tcp:" /proc/net/snmp'
section sysctl
try sysctl net.core.busy_poll net.core.busy_read kernel.timer_migration net.ipv4.tcp_min_rtt_wlen
section tcpdump; try command -v tcpdump
section namespaces; try ip netns list
