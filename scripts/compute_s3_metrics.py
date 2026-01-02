#!/usr/bin/env python3
"""
Compute S3 per-run metrics:
- state staleness at decision times
- correction propagation latency / inconsistency duration
Inputs:
- runs/_paper_s3_official_runs.txt
- runs/<run_id>/consumer_events.csv
Outputs:
- data/processed/results/paper_s3_official.csv
"""
from pathlib import Path
import pandas as pd

def main():
    runlist = Path("runs/_paper_s3_official_runs.txt")
    if not runlist.exists():
        raise SystemExit("Missing runs/_paper_s3_official_runs.txt")

    rows = []
    for rid in runlist.read_text().splitlines():
        ev_path = Path("runs")/rid/"consumer_events.csv"
        if not ev_path.exists():
            raise SystemExit(f"Missing {ev_path}")
        # TODO(implement): load events, compute staleness + correction propagation metrics
        rows.append({"run": rid})

    out = Path("data/processed/results/paper_s3_official.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"Wrote {out}")

if __name__ == "__main__":
    main()
