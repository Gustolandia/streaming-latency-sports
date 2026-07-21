#!/usr/bin/env python3
"""
make_replay_plan.py
Build a per-match replay plan from a raw StatsBomb events file.

This is the step that turns raw event JSON into the schedule the producers replay: each event
gets a match-clock position (t_sim_seconds) and an emission offset (t_emit_offset_s), the
latter divided by --speed-factor so a plan can bake in acceleration. The repository ships the
generated plans as data; this script is what regenerates them, so the corpus is reproducible
from the pinned upstream commit rather than taken on trust.

CLI:
    python scripts/make_replay_plan.py --commit <sha> --match-id 3895052 --speed-factor 120
"""
import argparse
import json
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd

PERIOD_OFFSET_S = {1: 0, 2: 45*60, 3: 90*60, 4: 105*60, 5: 120*60}

def safe_int(x, default=0):
    try:
        return int(x)
    except Exception:
        return default

def main(argv=None):
    ap = argparse.ArgumentParser(description="Build a per-match replay plan from raw StatsBomb events")
    ap.add_argument("--commit", required=True)
    ap.add_argument("--match-id", type=int, required=True)
    ap.add_argument("--raw-root", default="data/raw/statsbomb")
    ap.add_argument("--out-root", default="data/processed/replay_plans")
    ap.add_argument("--speed-factor", type=float, default=1.0, help="1.0=real-time; >1 accelerates replay")
    args = ap.parse_args(argv)

    raw_path = Path(args.raw_root) / args.commit / "events" / f"{args.match_id}.json"
    if not raw_path.exists():
        raise FileNotFoundError(f"Missing events file: {raw_path}")

    events = json.loads(raw_path.read_text(encoding="utf-8"))
    if not isinstance(events, list) or not events:
        raise ValueError("Events JSON did not look like a non-empty list")

    rows = []
    for idx, e in enumerate(events):
        period = safe_int(e.get("period"), 1)
        minute = safe_int(e.get("minute"), 0)
        second = safe_int(e.get("second"), 0)
        offset = PERIOD_OFFSET_S.get(period, 0)

        t_sim = offset + minute * 60 + second
        t_emit_offset = t_sim / float(args.speed_factor)

        rows.append({
            "row_idx": idx,
            "match_id": args.match_id,
            "event_id": e.get("id"),
            "period": period,
            "minute": minute,
            "second": second,
            "t_sim_seconds": t_sim,
            "t_emit_offset_s": t_emit_offset,
            "event_type": (e.get("type") or {}).get("name"),
            "team": (e.get("team") or {}).get("name"),
            "player": (e.get("player") or {}).get("name"),
            "timestamp": e.get("timestamp"),
            "possession": e.get("possession"),
            "payload": e,
        })

    df = pd.DataFrame(rows).sort_values(["t_sim_seconds", "row_idx"], kind="mergesort").reset_index(drop=True)

    out_dir = Path(args.out_root) / args.commit / f"match_{args.match_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    out_csv = out_dir / "replay_plan.csv"
    df.drop(columns=["payload"]).to_csv(out_csv, index=False)

    # The CSV is what the producers consume; the parquet copy additionally carries the raw
    # event payload and needs pyarrow. Treat it as optional so a missing engine cannot stop
    # the corpus being regenerated.
    out_parquet = out_dir / "replay_plan.parquet"
    parquet_written = False
    try:
        df.to_parquet(out_parquet, index=False)
        parquet_written = True
    except (ImportError, ValueError) as exc:
        print(f"WARNING: skipped parquet ({exc.__class__.__name__}: install pyarrow to enable)")

    meta = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "commit": args.commit,
        "match_id": args.match_id,
        "n_events": int(df.shape[0]),
        "speed_factor": args.speed_factor,
        "raw_events_path": str(raw_path),
        "outputs": {"csv_no_payload": str(out_csv),
                    "parquet_with_payload": str(out_parquet) if parquet_written else None},
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"OK: wrote {df.shape[0]} rows")
    print(f"  {out_csv}")
    if parquet_written:
        print(f"  {out_parquet}")
    print(f"  {out_dir / 'meta.json'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
