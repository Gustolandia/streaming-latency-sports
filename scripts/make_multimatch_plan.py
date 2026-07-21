#!/usr/bin/env python3
"""
make_multimatch_plan.py
Merge per-match replay plans into one deterministic multi-match plan.

Used to build the merged plans (e.g. s2sf12) in which a single feed carries several matches at
once. Kick-off jitter is derived deterministically from the match id and a seed, so the merged
schedule is reproducible. Note that a merged plan multiplies the per-feed event rate by the
number of matches it packs -- the confound discussed in the manuscript -- so prefer per-match
plans (--plans-dir on the orchestrator) when concurrency is the variable of interest.

CLI:
    python scripts/make_multimatch_plan.py --commit <sha> --match-ids-file configs/s2_match_ids.txt         --out-dir data/processed/replay_plans/s2sf12 --speed-factor 12
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import pandas as pd


def read_match_ids(path: Path) -> list[int]:
    ids: list[int] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        ids.append(int(line))
    if not ids:
        raise ValueError(f"No match IDs found in {path}")
    return ids


def deterministic_jitter(match_id: int, seed: int, max_abs_s: float) -> float:
    if max_abs_s <= 0:
        return 0.0
    r = random.Random(seed + match_id)
    return r.uniform(-max_abs_s, max_abs_s)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Merge per-match replay plans into a deterministic multi-match plan.")
    ap.add_argument("--commit", required=True)
    ap.add_argument("--match-ids-file", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--speed-factor", required=True, type=float)
    ap.add_argument("--kickoff-jitter-max-s", type=float, default=0.0)
    ap.add_argument("--jitter-seed", type=int, default=20260101)
    ap.add_argument("--max-events-per-match", type=int, default=0, help="0 = keep all events")
    ap.add_argument("--plans-root", default="data/processed/replay_plans",
                    help="Root holding <commit>/match_<id>/replay_plan.csv")
    args = ap.parse_args(argv)

    commit = args.commit
    match_ids = read_match_ids(args.match_ids_file)
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    frames = []
    kickoff_offsets = {}

    for match_order, mid in enumerate(match_ids):
        plan_path = Path(args.plans_root) / commit / f"match_{mid}" / "replay_plan.csv"
        if not plan_path.exists():
            raise FileNotFoundError(f"Missing per-match plan: {plan_path}")

        df = pd.read_csv(plan_path)

        required = {"t_sim_seconds", "t_emit_offset_s"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"{plan_path} missing columns: {sorted(missing)}")

        if args.max_events_per_match and args.max_events_per_match > 0:
            df = df.head(args.max_events_per_match).copy()

        kickoff = deterministic_jitter(mid, args.jitter_seed, args.kickoff_jitter_max_s)
        kickoff_offsets[str(mid)] = kickoff

        df = df.copy()
        df["match_id"] = mid
        df["match_order"] = match_order
        df["event_seq"] = range(len(df))

        # Recompute schedule deterministically from sim time and the chosen speed factor
        df["t_emit_offset_s"] = (df["t_sim_seconds"] / float(args.speed_factor)) + float(kickoff)

        frames.append(df)

    combined = pd.concat(frames, ignore_index=True)

    # Stable deterministic global ordering
    combined = combined.sort_values(
        ["t_emit_offset_s", "match_order", "event_seq"],
        kind="mergesort"
    ).reset_index(drop=True)

    combined["global_seq"] = range(len(combined))

    csv_path = out_dir / "combined_plan.csv"
    pq_path = out_dir / "combined_plan.parquet"
    meta_path = out_dir / "meta.json"

    combined.to_csv(csv_path, index=False)
    parquet_written = False
    try:
        combined.to_parquet(pq_path, index=False)
        parquet_written = True
    except (ImportError, ValueError) as exc:
        print(f"WARNING: skipped parquet ({exc.__class__.__name__}: install pyarrow to enable)")

    meta = {
        "commit": commit,
        "match_ids": match_ids,
        "n_matches": len(match_ids),
        "n_events_total": int(len(combined)),
        "speed_factor": float(args.speed_factor),
        "kickoff_jitter_max_s": float(args.kickoff_jitter_max_s),
        "jitter_seed": int(args.jitter_seed),
        "kickoff_offsets_s": kickoff_offsets,
        "inputs": {
            "match_ids_file": str(args.match_ids_file),
            "per_match_plan": str(Path(args.plans_root) / commit / "match_<id>" / "replay_plan.csv"),
        },
        "outputs": {
            "combined_plan_csv": str(csv_path),
            "combined_plan_parquet": str(pq_path) if parquet_written else None,
        },
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print("Wrote:")
    print(" ", csv_path)
    if parquet_written:
        print(" ", pq_path)
    print(" ", meta_path)
    print("n_events_total =", len(combined))
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
