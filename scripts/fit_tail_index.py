#!/usr/bin/env python3
"""
fit_tail_index.py
From a mechanism to a rule: the tail index of the stall distribution.

The paper establishes P(inversion) = P(stall > T_true) by manipulating both sides, but has no
formula -- nothing that predicts the rate from measurable quantities. Two attempts failed, and
both failed the same way: they were curves in rho, and rho is not the variable.

E-A10 supplies what those attempts lacked. It varies T_true over 77x at fixed load, so it probes
the stall distribution's SHAPE directly. If run-queue delay has a heavy tail with index alpha,

    P(stall > t) ~ C * t^(-alpha)      hence      P(inversion) ~ C * T_true^(-alpha)

which is a power law in T_true with no free load parameter at all. Fitting it turns the mechanism
into a rule, and the rule makes a prediction that a completely different instrument can check.

WHY ALPHA IS THE INTERESTING NUMBER RATHER THAN C. A tail index below 1 means the distribution
has no finite mean. That is not a curiosity: it explains, rather than merely restates, why the
cumulative scheduler counters in E-A7 could not account for the effect. Those counters estimate
means, and a mean of a distribution with alpha < 1 does not exist -- the sample mean wanders with
sample size instead of converging. An instrument built on averages is structurally blind to this
failure, which is a stronger statement than "the averages happened not to move much".

THE INDEPENDENT CHECK. E-A9 traces run-queue delay in the kernel and measures P(stall > 0.5 ms)
directly. The rule fitted here predicts that same quantity from a payload sweep. The two share no
data, no instrument and no estimator, so agreement is evidence and disagreement bounds the rule.

CLI:
    python scripts/fit_tail_index.py --sweep docs/results/model/ttrue_sweep.csv \
        --traced docs/results/model/runq_tail.csv --out docs/results/model
"""
import argparse
import csv
import math
from pathlib import Path

MIN_POINTS = 3          # below this a power law is drawn through noise
MIN_RANGE = 5.0         # T_true must span at least this factor for the slope to mean anything
AGREE_FACTOR = 3.0      # independent estimates within this factor count as agreeing


def load_sweep(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                t, p = float(r["transport_ms"]), float(r["inversion"])
            except (KeyError, ValueError, TypeError):
                continue
            if t > 0 and p > 0:
                rows.append({"pad_bytes": int(r.get("pad_bytes", 0)),
                             "transport_ms": t, "inversion": p})
    return sorted(rows, key=lambda r: r["transport_ms"])


def fit_power_law(rows):
    """Least squares on log P against log T. Returns alpha, C and R^2 in log space."""
    n = len(rows)
    if n < MIN_POINTS:
        return None
    lt = [math.log(r["transport_ms"]) for r in rows]
    lp = [math.log(r["inversion"]) for r in rows]
    mt, mp = sum(lt) / n, sum(lp) / n
    den = sum((x - mt) ** 2 for x in lt)
    if den <= 0:
        return None
    alpha = -sum((lt[i] - mt) * (lp[i] - mp) for i in range(n)) / den
    log_c = mp + alpha * mt
    ss_res = sum((lp[i] - (log_c - alpha * lt[i])) ** 2 for i in range(n))
    ss_tot = sum((x - mp) ** 2 for x in lp)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    span = rows[-1]["transport_ms"] / rows[0]["transport_ms"]
    return {"alpha": alpha, "C": math.exp(log_c), "r2_log": r2, "n": n, "span": span}


def moments_exist(alpha):
    """What a tail index implies about the distribution's moments."""
    return {"mean": alpha > 1.0, "variance": alpha > 2.0}


def cross_check(fit, traced_path, threshold_ms):
    """Predict P(stall > threshold) from the sweep and compare with the kernel trace."""
    if fit is None:
        return {"checked": False, "why": "no fit"}
    try:
        with open(traced_path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    except OSError:
        return {"checked": False, "why": "no traced artefact"}
    base = next((r for r in rows if r.get("arm") == "base"), None)
    if base is None:
        return {"checked": False, "why": "no ordinary-priority arm in the trace"}
    try:
        measured = float(base["p_tail"])
    except (KeyError, ValueError, TypeError):
        return {"checked": False, "why": "traced tail not readable"}
    predicted = fit["C"] * threshold_ms ** (-fit["alpha"])
    ratio = predicted / measured if measured > 0 else float("inf")
    return {"checked": True, "measured": measured, "predicted": predicted, "ratio": ratio,
            "agree": (1 / AGREE_FACTOR) <= ratio <= AGREE_FACTOR}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sweep", default="docs/results/model/ttrue_sweep.csv")
    ap.add_argument("--traced", default="docs/results/model/runq_tail.csv")
    ap.add_argument("--threshold-ms", type=float, default=0.5)
    ap.add_argument("--out", default="docs/results/model")
    args = ap.parse_args(argv)

    if not Path(args.sweep).exists():
        print(f"missing sweep artefact: {args.sweep}")
        return 1
    rows = load_sweep(args.sweep)
    if len(rows) < MIN_POINTS:
        print(f"need at least {MIN_POINTS} usable points, have {len(rows)}")
        return 1

    fit = fit_power_law(rows)
    print("== the sweep ==")
    print(f"  {'pad':>9} {'T_true (ms)':>12} {'P(inversion)':>13}")
    for r in rows:
        print(f"  {r['pad_bytes']:>9} {r['transport_ms']:>12.3f} {r['inversion']:>13.5f}")

    print("\n== fitted rule ==")
    print(f"  P(inversion) = {fit['C']:.3f} * T_true^(-{fit['alpha']:.3f})     [T_true in ms]")
    print(f"  R^2 in log-log {fit['r2_log']:.4f} over {fit['n']} points spanning "
          f"{fit['span']:.0f}x in T_true")
    if fit["span"] < MIN_RANGE:
        print(f"  WARNING: a span below {MIN_RANGE:.0f}x is too narrow to call this a tail index")

    m = moments_exist(fit["alpha"])
    print("\n== what the index implies ==")
    print(f"  alpha = {fit['alpha']:.3f}")
    print(f"  finite mean:     {'yes' if m['mean'] else 'NO'}")
    print(f"  finite variance: {'yes' if m['variance'] else 'NO'}")
    if not m["mean"]:
        print("  A distribution with alpha < 1 has no mean. The sample average wanders with")
        print("  sample size rather than converging, so an instrument built on averages is")
        print("  STRUCTURALLY blind to this failure -- which is why the cumulative scheduler")
        print("  counters could not account for the effect, rather than merely happening not to.")

    x = cross_check(fit, args.traced, args.threshold_ms)
    print(f"\n== independent check at T_true = {args.threshold_ms} ms ==")
    if not x["checked"]:
        print(f"  not checked: {x['why']}")
    else:
        print(f"  traced in the kernel : {x['measured']:.5f}")
        print(f"  predicted by the rule: {x['predicted']:.5f}")
        print(f"  ratio {x['ratio']:.2f}  ->  {'AGREE' if x['agree'] else 'DISAGREE'}")
        print("  These share no data, no instrument and no estimator: one is a power law fitted")
        print("  to a payload sweep, the other a kernel trace of run-queue delay.")
        if x["agree"] and x["ratio"] > 1:
            print("  The rule over-predicts, which is the expected direction: not every stall")
            print("  lands on a stamping instant, so the observed rate should sit below the")
            print("  probability that a stall of sufficient length occurred at all.")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / "tail_index.csv"
    with dest.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["quantity", "value", "detail"])
        w.writerow(["alpha", f"{fit['alpha']:.4f}", "tail index of the stall distribution"])
        w.writerow(["C", f"{fit['C']:.4f}", "prefactor, T_true in ms"])
        w.writerow(["r2_log", f"{fit['r2_log']:.4f}", f"{fit['n']} points, {fit['span']:.0f}x span"])
        w.writerow(["n_points", fit["n"], "sweep conditions used"])
        w.writerow(["finite_mean", m["mean"], "alpha > 1"])
        w.writerow(["finite_variance", m["variance"], "alpha > 2"])
        if x["checked"]:
            w.writerow(["traced_p_tail", f"{x['measured']:.5f}",
                        f"kernel trace at {args.threshold_ms} ms"])
            w.writerow(["predicted_p_tail", f"{x['predicted']:.5f}", "from the fitted rule"])
            w.writerow(["cross_check_ratio", f"{x['ratio']:.3f}", "predicted / traced"])
    print(f"\nwrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
