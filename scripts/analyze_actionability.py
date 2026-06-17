#!/usr/bin/env python3
"""
Issue 5 - Sports-domain actionability & production-system comparison.

The previous analysis emitted all-zero actionability because it read a
`tti_summary["actionability"]` key that the runs never contained. This script
computes actionability correctly from the `missed_window_rate` already present
in every tti_summary.json:

    pct_under(W) = (1 - missed_window_rate[W]) * 100

Windows are mapped to sports stakeholder use-cases, and results are compared to
published production-system latency budgets.

CLI:
    python scripts/analyze_actionability.py [--runs-dir runs] [--pattern 'batch*'] \
        [--out docs/results/actionability]
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

# Sports use-case -> max acceptable latency (ms). Windows must exist in tti_summary.
SPORTS_USE_CASES = {
    "betting": 100,
    "live_alert": 250,
    "coaching": 500,
    "broadcast": 1000,
    "fan_app": 5000,
}

# Published production-system latency budgets (ms) for context.
PRODUCTION_SYSTEMS = {
    "Hawk-Eye": 100,
    "Second Spectrum": 200,
    "Opta Sports": 500,
    "StatsBomb": 1000,
}


def actionability_from_rates(missed_window_rate, use_cases=None):
    """Convert {window_ms_str: miss_fraction} into {use_case: pct_under_threshold}."""
    use_cases = use_cases or SPORTS_USE_CASES
    out = {}
    for case, window in use_cases.items():
        key = str(window)
        if key in missed_window_rate and missed_window_rate[key] is not None:
            out[case] = (1.0 - float(missed_window_rate[key])) * 100.0
        else:
            out[case] = float("nan")
    return out


def load_run_actionability(run_dir):
    """Read one run's tti_summary.json and return its actionability row, or None."""
    run_dir = Path(run_dir)
    tti_path = run_dir / "tti_summary.json"
    if not tti_path.exists():
        return None
    try:
        with open(tti_path, encoding="utf-8-sig") as f:
            tti = json.load(f)
    except (ValueError, OSError):
        return None
    rates = tti.get("tti_ms", {}).get("missed_window_rate")
    if not rates:
        return None
    backend = "kafka" if "kafka" in run_dir.name else "redis" if "redis" in run_dir.name else "unknown"
    config = "cluster" if "cluster" in run_dir.name else "single" if "single" in run_dir.name else "n/a"
    row = {"run_id": run_dir.name, "backend": backend, "config": config}
    row.update({f"pct_under_{case}": v for case, v in actionability_from_rates(rates).items()})
    return row


def production_comparison(df, systems=None):
    """For each production system threshold, mean % of events meeting it, per backend."""
    systems = systems or PRODUCTION_SYSTEMS
    window_to_case = {w: c for c, w in SPORTS_USE_CASES.items()}
    rows = []
    for system, budget in systems.items():
        case = window_to_case.get(budget)
        col = f"pct_under_{case}" if case else None
        entry = {"system": system, "budget_ms": budget}
        if col and col in df.columns:
            for backend in sorted(df["backend"].dropna().unique()):
                vals = df[df["backend"] == backend][col].dropna()
                entry[f"{backend}_pct_meeting"] = round(float(vals.mean()), 2) if len(vals) else float("nan")
        rows.append(entry)
    return pd.DataFrame(rows)


def write_production_markdown(prod_df, path):
    """Write a small production-comparison markdown table."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Production-System Latency Comparison (Issue 5)",
        "",
        "Percentage of benchmarked events meeting each production system's latency budget.",
        "",
        "| System | Budget (ms) | " + " | ".join(
            c.replace("_pct_meeting", " (%)") for c in prod_df.columns if c.endswith("_pct_meeting")
        ) + " |",
        "|--------|-------------|" + "------|" * sum(c.endswith("_pct_meeting") for c in prod_df.columns),
    ]
    meet_cols = [c for c in prod_df.columns if c.endswith("_pct_meeting")]
    for _, r in prod_df.iterrows():
        cells = " | ".join(f"{r[c]:.1f}" if pd.notna(r[c]) else "n/a" for c in meet_cols)
        lines.append(f"| {r['system']} | {r['budget_ms']} | {cells} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Sports actionability & production comparison (Issue 5)")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--pattern", default="batch*")
    ap.add_argument("--out", default="docs/results/actionability")
    args = ap.parse_args(argv)

    runs_dir = Path(args.runs_dir)
    rows = []
    for run_dir in sorted(runs_dir.glob(args.pattern)):
        if not run_dir.is_dir():
            continue
        row = load_run_actionability(run_dir)
        if row is not None:
            rows.append(row)

    if not rows:
        print(f"No runs with missed_window_rate matched {args.pattern} in {runs_dir}")
        return 1

    df = pd.DataFrame(rows)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_dir / "actionability_by_run.csv", index=False)

    pct_cols = [c for c in df.columns if c.startswith("pct_under_")]
    by_backend = df.groupby("backend")[pct_cols].mean()
    by_backend.to_csv(out_dir / "actionability_by_backend.csv")

    prod = production_comparison(df)
    prod.to_csv(out_dir / "production_comparison.csv", index=False)
    write_production_markdown(prod, out_dir / "production_comparison.md")

    print(f"Analyzed {len(df)} runs. Actionability (% of events under threshold) by backend:")
    print(by_backend.to_string())
    print(f"Wrote results to {out_dir}/")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
