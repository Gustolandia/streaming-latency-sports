#!/usr/bin/env python3
"""
Issue 4 - Statistical power analysis.

Provides a-priori required-sample-size and post-hoc achieved-power calculations
for the two-sample comparisons used in the study, so the manuscript's sample
sizes can be justified. Uses statsmodels' TTestIndPower when available, with a
normal-approximation fallback so the module works without statsmodels.

CLI:
    python scripts/power_analysis.py [--n 20] [--alpha 0.05] [--power 0.8] \
        [--out docs/results/statistical_analysis/power_analysis.json]
"""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy import stats

ALPHA = 0.05
TARGET_POWER = 0.8
EFFECT_SIZES = {"small": 0.2, "medium": 0.5, "large": 0.8}

try:  # pragma: no cover - exercised indirectly
    from statsmodels.stats.power import TTestIndPower
    _ANALYSIS = TTestIndPower()
    _HAVE_SM = True
except Exception:  # pragma: no cover - statsmodels is optional and absent here
    _ANALYSIS = None
    _HAVE_SM = False


def achieved_power(effect_size, n_per_group, alpha=ALPHA):
    """Post-hoc power for a two-sided two-sample t-test."""
    if n_per_group < 2 or effect_size == 0:
        return 0.0
    if _HAVE_SM:
        return float(_ANALYSIS.power(effect_size=effect_size, nobs1=n_per_group,
                                     alpha=alpha, ratio=1.0, alternative="two-sided"))
    # Normal-approximation fallback
    ncp = abs(effect_size) * np.sqrt(n_per_group / 2.0)
    z_crit = stats.norm.ppf(1 - alpha / 2)
    return float(stats.norm.cdf(ncp - z_crit) + stats.norm.cdf(-ncp - z_crit))


def required_sample_size(effect_size, alpha=ALPHA, power=TARGET_POWER):
    """A-priori sample size per group for a target power (two-sided t-test)."""
    if effect_size == 0:
        return float("inf")
    if _HAVE_SM:
        n = _ANALYSIS.solve_power(effect_size=abs(effect_size), alpha=alpha,
                                  power=power, ratio=1.0, alternative="two-sided")
        return int(np.ceil(n))
    z_a = stats.norm.ppf(1 - alpha / 2)
    z_b = stats.norm.ppf(power)
    n = 2 * ((z_a + z_b) / abs(effect_size)) ** 2
    return int(np.ceil(n))


def analyze_power(n_per_group, alpha=ALPHA, power=TARGET_POWER, effect_sizes=None):
    """Build a power table across standard effect sizes for a given sample size."""
    effect_sizes = effect_sizes or EFFECT_SIZES
    results = {}
    for name, d in effect_sizes.items():
        results[name] = {
            "effect_size": d,
            "required_n_per_group": required_sample_size(d, alpha, power),
            "achieved_power_at_n": round(achieved_power(d, n_per_group, alpha), 4),
            "adequately_powered": achieved_power(d, n_per_group, alpha) >= power,
        }
    return {
        "n_per_group": n_per_group,
        "alpha": alpha,
        "target_power": power,
        "backend": "statsmodels" if _HAVE_SM else "normal-approx",
        "by_effect_size": results,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Statistical power analysis (Issue 4)")
    ap.add_argument("--n", type=int, default=20, help="Sample size per group (observed)")
    ap.add_argument("--alpha", type=float, default=ALPHA)
    ap.add_argument("--power", type=float, default=TARGET_POWER)
    ap.add_argument("--out", default="docs/results/statistical_analysis/power_analysis.json")
    args = ap.parse_args(argv)

    report = analyze_power(args.n, args.alpha, args.power)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"Power analysis (n={args.n}/group, alpha={args.alpha}, target power={args.power}, "
          f"engine={report['backend']}):")
    for name, r in report["by_effect_size"].items():
        flag = "OK" if r["adequately_powered"] else "UNDERPOWERED"
        print(f"  {name} (d={r['effect_size']}): need n>={r['required_n_per_group']}, "
              f"achieved power={r['achieved_power_at_n']} [{flag}]")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    import sys
    sys.exit(main())
