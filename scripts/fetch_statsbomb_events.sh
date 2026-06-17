#!/usr/bin/env bash
# Re-fetch the StatsBomb match event JSONs used by this study from the PINNED open-data
# commit (so the data is reproducible without bloating git with ~120 MB of raw JSON).
# Dataset: 1. Bundesliga 2023/24 (competition 9, season 281), 34 matches.
# Requires: bash + curl. Usage:  bash scripts/fetch_statsbomb_events.sh
set -euo pipefail
SHA=3bfbffe1de5750ebd47d770be0bb924a10cde54f
BASE="https://raw.githubusercontent.com/statsbomb/open-data/$SHA/data"
OUT="data/raw/statsbomb/$SHA/events"
mkdir -p "$OUT"
curl -sS --retry 3 --retry-delay 2 --max-time 60 -o matches.tmp "$BASE/matches/9/281.json"
python - <<'PY'
import json
ids=[str(m["match_id"]) for m in json.load(open("matches.tmp", encoding="utf-8"))]
open("ids.tmp","w",newline="\n").write("\n".join(ids)+"\n")
print(f"{len(ids)} matches queued")
PY
ok=0
while IFS= read -r id; do
  id=$(echo "$id" | tr -d '\r\n ')
  [ -z "$id" ] && continue
  code=$(curl -sS --retry 3 --retry-delay 2 --max-time 60 -o "$OUT/$id.json" -w '%{http_code}' "$BASE/events/$id.json")
  if [ "$code" = "200" ] && [ -s "$OUT/$id.json" ]; then ok=$((ok+1)); else rm -f "$OUT/$id.json"; echo "FAIL $id ($code)"; fi
  sleep 1
done < ids.tmp
rm -f matches.tmp ids.tmp
echo "fetched $ok match event files into $OUT"
