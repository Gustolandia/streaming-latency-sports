#!/usr/bin/env bash
# Stop this pair, from the pair itself, once there is no work left on it.
#
# Why this exists. A machine that has finished its list keeps billing until somebody notices, and
# nothing on the machine could do anything about it: there was no Azure CLI and no identity, so
# deallocating a pair could only be done from outside, by hand. Two days of unattended work meant
# two days in which the only thing standing between a finished pair and an empty subscription was
# somebody looking.
#
# What it may do, and nothing else. Each driver has a system-assigned identity holding one custom
# role, "SBL Pair Deallocator", scoped to its own resource group: read a virtual machine, and
# deallocate it. No create, no delete, no start, no restart -- asked to restart itself, a driver
# is refused with 403, and asked to read another pair's driver it is refused the same way. Each
# pair is its own resource group, so "every machine in my group" is exactly this pair and cannot
# be anything else.
#
# Deallocated is the word that matters. A machine shut down from inside is still allocated and
# still billed; only deallocation stops the charge, and it keeps the disks, so every run stays
# where it is and comes back with the machine.
#
# The broker goes first and this machine last, because this machine is the one whose last act
# this is.
. "$(dirname "${BASH_SOURCE[0]}")/../campaigns/common.sh"
set +e
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)" || exit 1

IMDS="http://169.254.169.254/metadata"
API="2023-03-01"
#: A resource group holding more machines than a pair is not a pair, and this stops rather than
#: guessing which of them it was meant to turn off.
MOST_IN_A_PAIR=4

log () { echo "$(date -u +%FT%TZ) stop-self: $*"; }

token () {
  curl -s -m 15 -H Metadata:true \
    "$IMDS/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/" \
    | python3 -c 'import json, sys
try:
    print(json.load(sys.stdin)["access_token"])
except Exception:
    raise SystemExit(1)' 2>/dev/null
}

whoami_here () {
  curl -s -m 15 -H Metadata:true "$IMDS/instance?api-version=2021-02-01" \
    | python3 -c 'import json, sys
try:
    one = json.load(sys.stdin)["compute"]
    print(one["subscriptionId"], one["resourceGroupName"], one["name"])
except Exception:
    raise SystemExit(1)' 2>/dev/null
}

main () {
  local tok sub rg me others
  tok=$(token) || true
  [ -n "$tok" ] || { log "no managed-identity token here; nothing can be stopped from inside"; exit 1; }
  read -r sub rg me <<< "$(whoami_here)"
  [ -n "$me" ] || { log "this machine could not read its own name from the metadata service"; exit 1; }
  log "I am $me in $rg"

  local listing
  listing=$(curl -s -m 30 -H "Authorization: Bearer $tok" \
    "https://management.azure.com/subscriptions/$sub/resourceGroups/$rg/providers/Microsoft.Compute/virtualMachines?api-version=$API")
  others=$(echo "$listing" | python3 -c 'import json, sys
mine = sys.argv[1]
try:
    found = [one["name"] for one in json.load(sys.stdin)["value"]]
except Exception:
    raise SystemExit(1)
if mine not in found or len(found) > int(sys.argv[2]):
    raise SystemExit(1)
print(" ".join(sorted(name for name in found if name != mine)))' "$me" "$MOST_IN_A_PAIR") \
    || { log "the group does not look like this pair; stopping nothing"; exit 1; }

  local vm code
  for vm in $others $me; do
    code=$(curl -s -o /dev/null -w "%{http_code}" -m 60 -X POST -H "Content-Length: 0" \
      -H "Authorization: Bearer $tok" \
      "https://management.azure.com/subscriptions/$sub/resourceGroups/$rg/providers/Microsoft.Compute/virtualMachines/$vm/deallocate?api-version=$API")
    log "  deallocate $vm -> HTTP $code"
  done
  log "asked for every machine in $rg; this one goes last and may not live to say so"
}

main "$@"
