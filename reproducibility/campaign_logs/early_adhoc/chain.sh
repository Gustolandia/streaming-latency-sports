#!/usr/bin/env bash
# Wait for campaign 2, then start campaign 3 without me babysitting the boundary.
while ! grep -q CAMPAIGN2_COMPLETE ~/campaign2.log 2>/dev/null; do sleep 30; done
bash ~/campaign3.sh > ~/campaign3.log 2>&1
echo "CHAIN_DONE $(date +%H:%M:%S)"
