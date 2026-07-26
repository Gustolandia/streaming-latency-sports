#!/usr/bin/env bash
while ! grep -q CAMPAIGN3_COMPLETE ~/campaign3.log 2>/dev/null; do sleep 30; done
bash ~/campaign4.sh > ~/campaign4.log 2>&1
echo "ALL_CAMPAIGNS_DONE $(date +%H:%M:%S)"
