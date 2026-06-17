#!/usr/bin/env python3
"""
Compute S4 per-run metrics from parameter sweep.
Directly processes S4 run outputs.

Usage:
    python scripts/compute_s4_metrics.py [--runlist RUNLIST] [--out OUTPUT]
"""
import json
import csv
from pathlib import Path
import pandas as pd
import numpy as np
import argparse
import sys


def compute_tti_percentiles(tti_values):
    if not tti_values:
        return {}
    arr = np.array(tti_values)
    return {
        "p50": float(np.median(arr)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
        "max": float(np.max(arr)),
        "mean": float(np.mean(arr)),
        "std": float(np.std(arr)),
        "min": float(np.min(arr)),
        "count": int(len(arr)),
    }


def extract_s4_config_from_runid(run_id):
    parts = run_id.split("_")
    valid_backends = ["kafka", "redis"]
    backend_idx = None
    for i, part in enumerate(parts):
        if part in valid_backends:
            backend_idx = i
            break
    if backend_idx is None or len(parts) < 2:
        return {}
    config_map = {
        "baseline": {"speedup": 120, "corrections_every_k": 50, "correction_delay_s": 2.0},
        "low_speedup": {"speedup": 60, "corrections_every_k": 50, "correction_delay_s": 2.0},
        "high_speedup": {"speedup": 240, "corrections_every_k": 50, "correction_delay_s": 2.0},
        "high_frequency": {"speedup": 120, "corrections_every_k": 10, "correction_delay_s": 2.0},
        "low_frequency": {"speedup": 120, "corrections_every_k": 100, "correction_delay_s": 2.0},
        "long_delay": {"speedup": 120, "corrections_every_k": 50, "correction_delay_s": 5.0},
        "short_delay": {"speedup": 120, "corrections_every_k": 50, "correction_delay_s": 0.5},
        "fast_corrections": {"speedup": 120, "corrections_every_k": 10, "correction_delay_s": 0.5},
    }
    scenario = parts[0] if len(parts) > 0 else None
    config_name = "_".join(parts[1:backend_idx]) if backend_idx > 1 else None
    backend = parts[backend_idx] if backend_idx is not None else None
    return {"scenario": scenario, "config": config_name, "backend": backend, **config_map.get(config_name, {})}


def load_tti_values(run_dir):
    tti_path = run_dir / "tti_summary.json"
    if not tti_path.exists():
        return []
    try:
        with open(tti_path, encoding='utf-8-sig') as f:
            data = json.load(f)
        # Check for raw TTI values
        if "tti_all_ms" in data:
            return data["tti_all_ms"]
        elif "tti_values" in data:
            return data["tti_values"]
        elif "tti_list" in data:
            return data["tti_list"]
        # If no raw values, we still return empty list - percentiles will be extracted separately
        return []
    except Exception as e:
        print(f"Warning: Could not load TTI from {run_dir}: {e}")
        return []


def compute_s4_metrics_for_run(run_dir):
    run_id = run_dir.name
    config_info = extract_s4_config_from_runid(run_id)
    tti_values = load_tti_values(run_dir)
    
    # Load tti_summary.json to extract percentiles directly
    tti_data = {}
    tti_path = run_dir / "tti_summary.json"
    if tti_path.exists():
        try:
            with open(tti_path, encoding='utf-8-sig') as f:
                tti_data = json.load(f)
        except Exception:
            pass
    
    meta = {}
    meta_path = run_dir / "meta.json"
    if meta_path.exists():
        try:
            with open(meta_path, encoding='utf-8-sig') as f:
                meta = json.load(f)
        except Exception:
            pass
    
    # If we have raw TTI values, compute percentiles from them
    if tti_values:
        tti_percentiles = compute_tti_percentiles(tti_values)
    else:
        # Otherwise extract from tti_ms field in summary
        tti_percentiles = {}
        if "tti_ms" in tti_data and isinstance(tti_data["tti_ms"], dict):
            for key in ["p50", "p95", "p99", "max", "mean", "std", "min"]:
                if key in tti_data["tti_ms"]:
                    tti_percentiles[key] = tti_data["tti_ms"][key]
        # Also include transport and producer_sched_lag if available
        for field in ["transport_ms", "producer_sched_lag_ms"]:
            if field in tti_data and isinstance(tti_data[field], dict):
                for key in ["p50", "p95", "p99", "max", "mean", "std", "min"]:
                    if key in tti_data[field]:
                        tti_percentiles[f"{field}_{key}"] = tti_data[field][key]
    n_producer = 0
    n_consumer = 0
    for fname, target in [("producer.csv", "n_producer"), ("consumer.csv", "n_consumer")]:
        fpath = run_dir / fname
        if fpath.exists():
            try:
                with open(fpath, encoding='utf-8-sig') as f:
                    reader = csv.reader(f)
                    next(reader, None)
                    count = sum(1 for _ in reader)
                    if target == "n_producer":
                        n_producer = count
                    else:
                        n_consumer = count
            except Exception:
                pass
    # Get n_tti_values from various sources
    n_tti = len(tti_values)
    if not n_tti and "n_matched" in tti_data:
        n_tti = tti_data["n_matched"]
    elif not n_tti and "n_consumed" in tti_data:
        n_tti = tti_data["n_consumed"]
    
    metrics = {
        "run": run_id, "scenario": config_info.get("scenario", ""),
        "config": config_info.get("config", ""), "backend": config_info.get("backend", ""),
        "speedup": config_info.get("speedup", 0), "corrections_every_k": config_info.get("corrections_every_k", 0),
        "correction_delay_s": config_info.get("correction_delay_s", 0.0),
        "n_producer_events": n_producer, "n_consumer_events": n_consumer,
        "n_tti_values": n_tti,
    }
    
    # Add TTI percentiles
    for key, value in tti_percentiles.items():
        metrics[f"tti_{key}"] = value
    
    # Add matched events info
    for key in ["n_produced", "n_consumed", "n_matched"]:
        if key in tti_data:
            metrics[key] = tti_data[key]
    
    for key in ["plan_csv", "max_t_sim"]:
        if key in meta:
            metrics[f"meta_{key}"] = meta[key]
    
    # Add missed window rates if available
    if "tti_ms" in tti_data and isinstance(tti_data["tti_ms"], dict):
        if "missed_window_rate" in tti_data["tti_ms"]:
            for window, rate in tti_data["tti_ms"]["missed_window_rate"].items():
                metrics[f"missed_window_{window}ms_rate"] = rate
    
    return metrics


def main():
    parser = argparse.ArgumentParser(description="Compute S4 parameter sweep metrics")
    parser.add_argument("--runlist", default="runs/_paper_s4_parameter_sweep.txt", help="Path to S4 run list file")
    parser.add_argument("--out", default="data/processed/results/paper_s4_parameter_sweep.csv", help="Output CSV path")
    args = parser.parse_args()
    runlist = Path(args.runlist)
    if not runlist.exists():
        print(f"Missing {runlist}")
        sys.exit(1)
    rows = []
    for rid in runlist.read_text().splitlines():
        rid = rid.strip()
        if not rid or rid.startswith("#"):
            continue
        if rid.startswith("runs\\"):
            rid = rid.replace("runs\\", "")
        elif rid.startswith("runs/"):
            rid = rid.replace("runs/", "")
        run_dir = Path("runs") / rid
        if not run_dir.exists():
            print(f"Missing {run_dir}")
            sys.exit(1)
        metrics = compute_s4_metrics_for_run(run_dir)
        rows.append(metrics)
        print(f"Computed S4 metrics for {rid}: {metrics.get('n_tti_values', 0)} TTI values")
    df = pd.DataFrame(rows)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"Wrote {out}")
    summary = {
        "total_runs": len(rows),
        "total_tti_values": int(df["n_tti_values"].sum()) if "n_tti_values" in df.columns else 0,
        "scenarios": sorted(df["scenario"].unique().tolist()) if "scenario" in df.columns else [],
        "configs": sorted(df["config"].unique().tolist()) if "config" in df.columns else [],
        "backends": sorted(df["backend"].unique().tolist()) if "backend" in df.columns else [],
    }
    summary_path = Path(args.out).parent / (Path(args.out).stem + "_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"Wrote summary: {summary_path}")


if __name__ == "__main__":
    main()
