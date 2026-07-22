#!/usr/bin/env bash
# Apply/clear one-way egress delay on the broker NIC. Install on each broker host as ~/netem.sh
#
# limit is far above the default 1000 packets deliberately. At 20 ms with the default limit the
# netem queue overflows under our burst and TCP retransmission backoff imposes a flat multi-second
# stall that has nothing to do with the application: the shaper becomes the experiment. We tested
# this (1000 -> 200000) and it did NOT explain the multi-host anomaly, but the guard stays.
set -euo pipefail
DEV=$(ip route show default | awk '{print $5}' | head -1)
sudo tc qdisc del dev "$DEV" root 2>/dev/null || true
if [ "${1:-0}" != "0" ]; then
  sudo tc qdisc add dev "$DEV" root netem delay "$1"ms limit 200000
fi
tc qdisc show dev "$DEV"
