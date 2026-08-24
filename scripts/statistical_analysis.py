#!/usr/bin/env python3
"""
Issue 4 - Rigorous statistical analysis utilities.

Backs the statistical framework claimed in paper.tex with actually-computed
values: Holm-Bonferroni correction for multiple comparisons (FWER control),
effect sizes (Cohen's d, Hedges' g), 95% confidence intervals, and assumption
checks (Shapiro-Wilk normality, Levene equal-variance) driving automatic
parametric/non-parametric test selection.

CLI:
    python scripts/statistical_analysis.py [--runs-dir runs] [--pattern 'batch*'] \
        [--out docs/results/statistical_analysis]
"""
import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ALPHA = 0.05
RUN_RE = re.compile(r"(kafka|redis)_(single|cluster)_([a-z0-9]+)_n(\d+)_rep(\d+)")


# --------------------------------------------------------------------------- #
# Effect sizes & intervals
# --------------------------------------------------------------------------- #
def cohens_d(a, b):
    """Cohen's d for two independent samples (pooled SD)."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return float("nan")
    pooled = np.sqrt(((na - 1) * a.var(ddof=1) + (nb - 1) * b.var(ddof=1)) / (na + nb - 2))
    if pooled == 0:
        return 0.0
    return float((a.mean() - b.mean()) / pooled)


def hedges_g(a, b):
    """Hedges' g: small-sample bias-corrected Cohen's d."""
    d = cohens_d(a, b)
    n = len(a) + len(b)
    if n <= 2 or np.isnan(d):
        return d
    correction = 1.0 - 3.0 / (4.0 * n - 9.0)
    return float(d * correction)


def interpret_effect(d):
    """Qualitative label for an effect size magnitude."""
    ad = abs(d)
    if np.isnan(ad):
        return "undefined"
    if ad < 0.2:
        return "negligible"
    if ad < 0.5:
        return "small"
    if ad < 0.8:
        return "medium"
    return "large"


def confidence_interval(data, confidence=0.95):
    """t-distribution based CI for the mean. Returns (low, high)."""
    data = np.asarray(data, dtype=float)
    n = len(data)
    if n < 2:
        return (float("nan"), float("nan"))
    mean = data.mean()
    se = data.std(ddof=1) / np.sqrt(n)
    h = se * stats.t.ppf((1 + confidence) / 2, n - 1)
    return (float(mean - h), float(mean + h))


# --------------------------------------------------------------------------- #
# Assumption checks & test selection
# --------------------------------------------------------------------------- #
def check_normality(data, alpha=ALPHA):
    """Shapiro-Wilk; returns True if data look normal (or are too few to test)."""
    data = np.asarray(data, dtype=float)
    if len(data) < 3:
        return True
    _, p = stats.shapiro(data)
    return bool(p > alpha)


def check_equal_variance(a, b, alpha=ALPHA):
    """Levene's test; returns True if variances look equal."""
    if len(a) < 2 or len(b) < 2:
        return True
    _, p = stats.levene(np.asarray(a, float), np.asarray(b, float))
    return bool(p > alpha)


def compare_two_groups(a, b, label="", alpha=ALPHA):
    """Compare two groups, auto-selecting parametric vs non-parametric test."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    normal = check_normality(a, alpha) and check_normality(b, alpha)
    equal_var = check_equal_variance(a, b, alpha)
    if normal:
        stat, p = stats.ttest_ind(a, b, equal_var=equal_var)
        test = "Student t-test" if equal_var else "Welch t-test"
    else:
        stat, p = stats.mannwhitneyu(a, b, alternative="two-sided")
        test = "Mann-Whitney U"
    d = cohens_d(a, b)
    return {
        "label": label,
        "test": test,
        "statistic": float(stat),
        "p_value": float(p),
        "cohens_d": d,
        "hedges_g": hedges_g(a, b),
        "effect": interpret_effect(d),
        "ci_a": confidence_interval(a),
        "ci_b": confidence_interval(b),
        "normal": normal,
        "equal_var": equal_var,
        "n_a": int(len(a)),
        "n_b": int(len(b)),
        "mean_a": float(a.mean()) if len(a) else float("nan"),
        "mean_b": float(b.mean()) if len(b) else float("nan"),
    }


# --------------------------------------------------------------------------- #
# Multiple-comparison correction
# --------------------------------------------------------------------------- #
def holm_bonferroni(p_values, alpha=ALPHA):
    """Holm-Bonferroni step-down correction. Returns list of dicts in input order."""
    p = np.asarray(p_values, dtype=float)
    m = len(p)
    if m == 0:
        return []
    order = np.argsort(p)
    adjusted = np.empty(m)
    running = 0.0
    for rank, idx in enumerate(order):
        running = max(running, (m - rank) * p[idx])
        adjusted[idx] = min(running, 1.0)
    return [
        {"p_value": float(p[i]), "p_adjusted": float(adjusted[i]), "reject": bool(adjusted[i] < alpha)}
        for i in range(m)
    ]


# --------------------------------------------------------------------------- #
# Data loading & analysis pipeline
# --------------------------------------------------------------------------- #
def load_run_metrics(runs_dir, pattern="batch*"):
    """Read per-run tti_summary.json into a tidy DataFrame."""
    runs_dir = Path(runs_dir)
    rows = []
    for run_dir in sorted(runs_dir.glob(pattern)):
        if not run_dir.is_dir():
            continue
        tti_path = run_dir / "tti_summary.json"
        if not tti_path.exists():
            continue
        try:
            with open(tti_path, encoding="utf-8-sig") as f:
                tti = json.load(f)
        except (ValueError, OSError):
            continue
        block = tti.get("tti_ms", {})
        m = RUN_RE.search(run_dir.name)
        rows.append({
            "run_id": run_dir.name,
            "backend": m.group(1) if m else None,
            "config": m.group(2) if m else None,
            "scenario": m.group(3) if m else None,
            "n": int(m.group(4)) if m else None,
            "p50": block.get("p50"),
            "p95": block.get("p95"),
        })
    return pd.DataFrame(rows)


def kruskal_test(groups, label):
    """Kruskal-Wallis omnibus across >=2 non-empty groups (list of arrays)."""
    groups = [np.asarray(g, dtype=float) for g in groups if len(g) > 0]
    if len(groups) < 2:
        return None
    h, p = stats.kruskal(*groups)
    return {
        "label": label,
        "test": "Kruskal-Wallis",
        "statistic": float(h),
        "p_value": float(p),
        "k_groups": len(groups),
        "n_total": int(sum(len(g) for g in groups)),
    }


def run_family(df, metric="p50", alpha=ALPHA):
    """Run the comparison family (RQ1, Issue-2 config effect, RQ4 scenario) and apply
    Holm-Bonferroni across all p-values for FWER control."""
    comparisons = []
    if "backend" in df.columns and df["backend"].notna().any():
        backends = sorted(b for b in df["backend"].dropna().unique())
        # RQ1: kafka vs redis, overall and per config
        kafka = df[df["backend"] == "kafka"][metric].dropna()
        redis = df[df["backend"] == "redis"][metric].dropna()
        if len(kafka) >= 2 and len(redis) >= 2:
            comparisons.append(compare_two_groups(kafka, redis, "kafka_vs_redis_overall", alpha))
        if "config" in df.columns:
            for cfg in sorted(c for c in df["config"].dropna().unique()):
                k = df[(df["backend"] == "kafka") & (df["config"] == cfg)][metric].dropna()
                r = df[(df["backend"] == "redis") & (df["config"] == cfg)][metric].dropna()
                if len(k) >= 2 and len(r) >= 2:
                    comparisons.append(compare_two_groups(k, r, f"kafka_vs_redis_{cfg}", alpha))
            # Issue 2: single vs cluster, per backend
            for b in backends:
                single = df[(df["backend"] == b) & (df["config"] == "single")][metric].dropna()
                cluster = df[(df["backend"] == b) & (df["config"] == "cluster")][metric].dropna()
                if len(single) >= 2 and len(cluster) >= 2:
                    comparisons.append(compare_two_groups(single, cluster, f"single_vs_cluster_{b}", alpha))
        # RQ4: scenario effect (omnibus), per backend
        if "scenario" in df.columns:
            scenarios = sorted(s for s in df["scenario"].dropna().unique())
            for b in backends:
                groups = [df[(df["backend"] == b) & (df["scenario"] == s)][metric].dropna().values
                          for s in scenarios]
                kt = kruskal_test(groups, f"scenario_effect_{b}")
                if kt is not None:
                    comparisons.append(kt)

    corrected = holm_bonferroni([c["p_value"] for c in comparisons], alpha)
    for comp, adj in zip(comparisons, corrected):
        comp["p_adjusted"] = adj["p_adjusted"]
        comp["reject_after_correction"] = adj["reject"]
    return comparisons


def main(argv=None):
    ap = argparse.ArgumentParser(description="Rigorous statistical analysis (Issue 4)")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--pattern", default="batch*")
    ap.add_argument("--metric", default="p50")
    ap.add_argument("--out", default="docs/results/statistical_analysis")
    args = ap.parse_args(argv)

    df = load_run_metrics(args.runs_dir, args.pattern)
    if df.empty:
        print(f"No runs with tti_summary.json matched {args.pattern} in {args.runs_dir}")
        return 1

    comparisons = run_family(df, args.metric)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "statistical_analysis.json", "w", encoding="utf-8") as f:
        json.dump({"alpha": ALPHA, "metric": args.metric, "comparisons": comparisons}, f, indent=2)
    pd.DataFrame(comparisons).to_csv(out_dir / "statistical_analysis.csv", index=False)

    print(f"Analyzed {len(df)} runs; {len(comparisons)} comparisons (Holm-Bonferroni corrected).")
    for c in comparisons:
        effect = f" d={c['cohens_d']:.3f} ({c['effect']})" if "cohens_d" in c else ""
        verdict = "reject H0" if c["reject_after_correction"] else "retain H0"
        print(f"  {c['label']}: {c['test']} p={c['p_value']:.4g} "
              f"p_adj={c['p_adjusted']:.4g}{effect} -> {verdict}")
    print(f"Wrote results to {out_dir}/")
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    import sys
    sys.exit(main())
