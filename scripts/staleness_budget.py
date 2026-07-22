#!/usr/bin/env python3
"""
staleness_budget.py
Place measured transport latency inside the end-to-end staleness budget of a football feed.

The benchmark measures one term. A decision-maker experiences the sum. Between the moment a
pass is played and the moment a model can act on it there is:

    annotation  ->  transport  ->  inference

Annotation is the dominant term by orders of magnitude. Live football event data is hand-coded
by trained operators watching the match, and vendor descriptions of that pipeline put the lag
in the seconds. There is no peer-reviewed measurement of it, so a single number would be false
precision: this script sweeps annotation latency across a plausible range and reports what
share of total staleness each term owns at every point.

That sweep is the honest form of the paper's central claim. If infrastructure is 0.1% of the
budget the choice of broker cannot matter; the interesting question is what would have to be
true for it to matter, and the sweep answers it directly by finding the annotation latency at
which transport becomes non-negligible.

CLI:
    python scripts/staleness_budget.py --transport-ms 1.3 --out docs/results/football/budget
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

# Vendor-reported figures for live football event collection, in seconds. These are CLAIMS,
# not measurements, and are labelled as such wherever they are reported.
ANNOTATION_RANGE_S = (1.0, 30.0)
ANNOTATION_TYPICAL_S = 15.0


def budget(annotation_s, transport_ms, inference_ms=0.0):
    """Share of end-to-end staleness owned by each term."""
    a_ms = float(annotation_s) * 1000.0
    total = a_ms + float(transport_ms) + float(inference_ms)
    if total <= 0:
        return None
    return {
        "annotation_s": float(annotation_s),
        "annotation_ms": a_ms,
        "transport_ms": float(transport_ms),
        "inference_ms": float(inference_ms),
        "total_ms": total,
        "transport_share": float(transport_ms) / total,
        "annotation_share": a_ms / total,
        "transport_share_pct": 100.0 * float(transport_ms) / total,
    }


def sweep(transport_ms, inference_ms=0.0, lo_s=ANNOTATION_RANGE_S[0],
          hi_s=ANNOTATION_RANGE_S[1], n=30):
    """Budget across the plausible annotation range, log-spaced."""
    if hi_s <= 0 or lo_s <= 0 or n < 1:
        return pd.DataFrame()
    points = np.logspace(np.log10(lo_s), np.log10(hi_s), int(n))
    rows = [budget(a, transport_ms, inference_ms) for a in points]
    return pd.DataFrame([r for r in rows if r is not None])


def annotation_for_share(transport_ms, target_share, inference_ms=0.0):
    """Annotation latency at which transport owns exactly `target_share` of the budget.

    Inverts the budget algebraically. This is the number that answers "what would have to be
    true for infrastructure to matter?" - if the answer is an annotation latency far below
    anything a human pipeline achieves, the infrastructure term is structurally irrelevant.
    """
    t = float(transport_ms)
    if not 0 < target_share < 1 or t <= 0:
        return float("nan")
    # share = t / (a + t + i)  =>  a = t/share - t - i
    a_ms = t / target_share - t - float(inference_ms)
    return a_ms / 1000.0 if a_ms > 0 else 0.0


def compare_backends(transport_by_backend, annotation_s=ANNOTATION_TYPICAL_S, inference_ms=0.0):
    """End-to-end staleness per backend, and the difference between them as a share.

    The key output is `diff_share_pct`: the fraction of end-to-end staleness attributable to
    CHOOSING one backend over the other, which is the quantity a practitioner actually faces.
    """
    rows = []
    for name, t_ms in sorted(transport_by_backend.items()):
        b = budget(annotation_s, t_ms, inference_ms)
        if b:
            b["backend"] = name
            rows.append(b)
    df = pd.DataFrame(rows)
    if len(df) == 2:
        spread = float(df["transport_ms"].max() - df["transport_ms"].min())
        df["backend_spread_ms"] = spread
        df["diff_share_pct"] = 100.0 * spread / float(df["total_ms"].max())
    return df


def main(argv=None):
    ap = argparse.ArgumentParser(description="End-to-end staleness budget")
    ap.add_argument("--transport-ms", type=float, required=True,
                    help="measured broker transport (median), ms")
    ap.add_argument("--transport-alt-ms", type=float, default=None,
                    help="the other backend's transport, to price the choice between them")
    ap.add_argument("--inference-ms", type=float, default=0.0)
    ap.add_argument("--annotation-lo", type=float, default=ANNOTATION_RANGE_S[0])
    ap.add_argument("--annotation-hi", type=float, default=ANNOTATION_RANGE_S[1])
    ap.add_argument("--out", default="docs/results/football/budget")
    args = ap.parse_args(argv)

    sw = sweep(args.transport_ms, args.inference_ms, args.annotation_lo, args.annotation_hi)
    if sw.empty:
        print("Invalid annotation range")
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sw.to_csv(out / "annotation_sweep.csv", index=False)

    typical = budget(ANNOTATION_TYPICAL_S, args.transport_ms, args.inference_ms)
    a_1pct = annotation_for_share(args.transport_ms, 0.01, args.inference_ms)
    a_10pct = annotation_for_share(args.transport_ms, 0.10, args.inference_ms)

    print("== end-to-end staleness budget ==")
    print(f"transport (measured)        : {args.transport_ms:.3f} ms")
    print(f"annotation (vendor CLAIM)   : {ANNOTATION_TYPICAL_S:g} s typical, "
          f"{args.annotation_lo:g}-{args.annotation_hi:g} s swept")
    print(f"transport share at typical  : {typical['transport_share_pct']:.4f}%")
    print(f"annotation for 1% share     : {a_1pct:.3f} s")
    print(f"annotation for 10% share    : {a_10pct:.3f} s")

    if args.transport_alt_ms is not None:
        cmp_df = compare_backends(
            {"a": args.transport_ms, "b": args.transport_alt_ms},
            ANNOTATION_TYPICAL_S, args.inference_ms)
        cmp_df.to_csv(out / "backend_comparison.csv", index=False)
        if "diff_share_pct" in cmp_df.columns:
            print(f"backend choice is worth      : "
                  f"{cmp_df['backend_spread_ms'].iloc[0]:.3f} ms = "
                  f"{cmp_df['diff_share_pct'].iloc[0]:.4f}% of end-to-end staleness")
    print(f"\nWrote {out}/")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
