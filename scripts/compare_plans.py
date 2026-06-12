#!/usr/bin/env python
from pathlib import Path
import argparse
import pandas as pd
import numpy as np

# Enable coverage for subprocess execution if COVERAGE_PROCESS_START is set
try:
    import os
    if os.environ.get('COVERAGE_PROCESS_START'):
        import coverage
        coverage.process_start()
except Exception:
    pass

def infer_col(df, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    return None

def infer_match_col(df):
    prefs = ["match_id","game_id","fixture_id","match","game","fixture","matchId","gameId","fixtureId"]
    c = infer_col(df, prefs)
    if c:
        return c
    tokens = ("match","game","fixture")
    for col in df.columns:
        lo = col.lower()
        if any(t in lo for t in tokens):
            nunq = df[col].nunique(dropna=True)
            if nunq > 1 and nunq < max(5000, len(df)//2):
                return col
    return None

def infer_time_col(df):
    candidates = [
        "emit_ts_ms","emit_time_ms","scheduled_ts_ms","scheduled_time_ms",
        "emit_ms","scheduled_ms","t_emit_ms","t_scheduled_ms",
        "t_emit","scheduled","emit_time","emit",
        "wall_ms","wall_time_ms",
        "sim_ts_ms","sim_time_ms","event_ts_ms","event_time_ms",
        "sim_ms","event_ms","ts_ms","t_ms",
    ]
    c = infer_col(df, candidates)
    if c:
        return c
    timeish = []
    for col in df.columns:
        lo = col.lower()
        if any(k in lo for k in ("sched","emit","time","ts")) and pd.api.types.is_numeric_dtype(df[col]):
            timeish.append(col)
    return timeish[0] if timeish else None

def colsig(df):
    return {c: str(df[c].dtype) for c in df.columns}

def summarize_plan(name, path, df):
    match_col = infer_match_col(df)
    time_col = infer_time_col(df)

    overview = {
        "plan": name,
        "path": str(path),
        "n_rows": int(len(df)),
        "n_cols": int(df.shape[1]),
        "match_col": match_col or "",
        "time_col": time_col or "",
        "n_matches": int(df[match_col].nunique(dropna=True)) if match_col else np.nan,
    }

    if time_col and pd.api.types.is_numeric_dtype(df[time_col]):
        t = df[time_col].dropna().astype(float)
        if len(t):
            overview["time_min"] = float(t.min())
            overview["time_max"] = float(t.max())
            overview["time_span"] = float(t.max() - t.min())
        else:
            overview["time_min"] = overview["time_max"] = overview["time_span"] = np.nan
    else:
        overview["time_min"] = overview["time_max"] = overview["time_span"] = np.nan

    return overview, match_col, time_col

def gap_quantiles(df, plan_name, time_col):
    t = df[time_col].dropna()
    if not pd.api.types.is_numeric_dtype(t):
        return None
    t = t.astype(float).sort_values()
    gaps = t.diff().dropna()
    if gaps.empty:
        return None
    qs = [0, .5, .9, .95, .99, 1.0]
    out = {"plan": plan_name, "time_col": time_col, "n_gaps": int(len(gaps)), "gap_mean": float(gaps.mean())}
    for q in qs:
        out["gap_q%02d" % int(q*100)] = float(gaps.quantile(q))
    return out

def by_match(df, plan_name, match_col, time_col):
    g = df.groupby(match_col, dropna=False).size().rename("n_rows").reset_index()
    g["plan"] = plan_name
    if time_col and time_col in df.columns and pd.api.types.is_numeric_dtype(df[time_col]):
        t = df[[match_col, time_col]].dropna()
        if not t.empty:
            agg = t.groupby(match_col)[time_col].agg(["min","max"]).reset_index()
            agg["span"] = agg["max"] - agg["min"]
            g = g.merge(agg, on=match_col, how="left")
    return g

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="Path to plan A combined_plan.csv")
    ap.add_argument("--b", required=True, help="Path to plan B combined_plan.csv")
    ap.add_argument("--name-a", default="plan_a")
    ap.add_argument("--name-b", default="plan_b")
    ap.add_argument("--outdir", default="docs/results")
    args = ap.parse_args()

    A = Path(args.a)
    B = Path(args.b)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if not A.exists():
        raise SystemExit(f"Missing plan A: {A}")
    if not B.exists():
        raise SystemExit(f"Missing plan B: {B}")

    dfa = pd.read_csv(A)
    dfb = pd.read_csv(B)

    oa, a_match, a_time = summarize_plan(args.name_a, A, dfa)
    ob, b_match, b_time = summarize_plan(args.name_b, B, dfb)

    pd.DataFrame([oa, ob]).to_csv(outdir/"plan_compare_overview.csv", index=False)

    sa, sb = colsig(dfa), colsig(dfb)
    only_a = sorted(set(sa) - set(sb))
    only_b = sorted(set(sb) - set(sa))
    both = sorted(set(sa) & set(sb))
    dtype_diff = [(c, sa[c], sb[c]) for c in both if sa[c] != sb[c]]

    lines = []
    lines.append("=== PLAN A ===")
    lines.append(str(A))
    lines.append("=== PLAN B ===")
    lines.append(str(B))
    lines.append("")
    lines.append("Columns only in A (%d): %s" % (len(only_a), only_a))
    lines.append("Columns only in B (%d): %s" % (len(only_b), only_b))
    lines.append("Columns in both with dtype differences (%d): %s" % (len(dtype_diff), dtype_diff))
    lines.append("")
    lines.append("Inferred A match_col=%s, time_col=%s" % (a_match, a_time))
    lines.append("Inferred B match_col=%s, time_col=%s" % (b_match, b_time))
    (outdir/"plan_compare_columns.txt").write_text("\n".join(lines) + "\n")

    gaps = []
    if a_time:
        q = gap_quantiles(dfa, args.name_a, a_time)
        if q: gaps.append(q)
    if b_time:
        q = gap_quantiles(dfb, args.name_b, b_time)
        if q: gaps.append(q)
    pd.DataFrame(gaps).to_csv(outdir/"plan_compare_gap_quantiles.csv", index=False)

    bm = []
    if a_match:
        bm.append(by_match(dfa, args.name_a, a_match, a_time))
    if b_match:
        bm.append(by_match(dfb, args.name_b, b_match, b_time))
    if bm:
        pd.concat(bm, ignore_index=True).to_csv(outdir/"plan_compare_by_match.csv", index=False)
    else:
        pd.DataFrame(columns=["plan","match_id","n_rows"]).to_csv(outdir/"plan_compare_by_match.csv", index=False)

    print("Wrote:")
    print(" - %s" % (outdir/"plan_compare_overview.csv"))
    print(" - %s" % (outdir/"plan_compare_columns.txt"))
    print(" - %s" % (outdir/"plan_compare_gap_quantiles.csv"))
    print(" - %s" % (outdir/"plan_compare_by_match.csv"))

if __name__ == "__main__":
    main()
