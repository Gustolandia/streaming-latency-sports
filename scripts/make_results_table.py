import argparse, json
from pathlib import Path
import pandas as pd

# Enable coverage for subprocess execution if COVERAGE_PROCESS_START is set
try:
    import os
    if os.environ.get('COVERAGE_PROCESS_START'):
        import coverage
        coverage.process_start()
except Exception:
    pass

WINDOWS = ["100","250","500","1000","2000","5000"]

def get_nested(d, path, default=None):
    cur = d
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur

def load_summary(run_dir: Path):
    p = run_dir / "tti_summary.json"
    if not p.exists():
        return None

    d = json.loads(p.read_text(encoding="utf-8"))

    row = {
        "run": run_dir.name,
        "backend": "kafka" if "kafka" in run_dir.name else ("redis" if "redis" in run_dir.name else "unknown"),
        "n_produced": d.get("n_produced"),
        "n_consumed": d.get("n_consumed"),
        "n_matched": d.get("n_matched"),

        "tti_p50_ms": get_nested(d, ["tti_ms","p50"]),
        "tti_p95_ms": get_nested(d, ["tti_ms","p95"]),
        "tti_p99_ms": get_nested(d, ["tti_ms","p99"]),
        "tti_max_ms": get_nested(d, ["tti_ms","max"]),

        "transport_p50_ms": get_nested(d, ["transport_ms","p50"]),
        "transport_p95_ms": get_nested(d, ["transport_ms","p95"]),
        "transport_p99_ms": get_nested(d, ["transport_ms","p99"]),
        "transport_max_ms": get_nested(d, ["transport_ms","max"]),

        "schedlag_p50_ms": get_nested(d, ["producer_sched_lag_ms","p50"]),
        "schedlag_p95_ms": get_nested(d, ["producer_sched_lag_ms","p95"]),
        "schedlag_p99_ms": get_nested(d, ["producer_sched_lag_ms","p99"]),
        "schedlag_max_ms": get_nested(d, ["producer_sched_lag_ms","max"]),
    }

    # Missed-window rates (optional)
    for w in WINDOWS:
        row[f"tti_miss_{w}ms"] = get_nested(d, ["tti_ms","missed_window_rate", w])
        row[f"schedlag_miss_{w}ms"] = get_nested(d, ["producer_sched_lag_ms","missed_window_rate", w])

    return row

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rows = []
    skipped = 0
    for r in args.runs:
        p = Path(r)
        if not p.exists():
            alt = Path("runs") / r
            if alt.exists():
                p = alt
        row = load_summary(p)
        if row is None:
            skipped += 1
            continue
        rows.append(row)

    if not rows:

        print("No runs loaded (all skipped). Did you pass RUN_IDs instead of runs/<RUN_ID> paths?")

        return

    

    df = pd.DataFrame(rows).sort_values(["backend","run"])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)

    print(df.to_string(index=False))
    if skipped:
        print(f"\nNOTE: skipped {skipped} run(s) without tti_summary.json")

if __name__ == "__main__":
    main()
