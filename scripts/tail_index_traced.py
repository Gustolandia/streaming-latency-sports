#!/usr/bin/env python3
"""
tail_index_traced.py
Estimate the run-queue stall tail index from the kernel trace, with an interval.

Why this exists. The manuscript reported an effective exponent from a four-point log-log
regression over the payload sweep, and cross-checked it against a "windowed log-log index"
read off the traced histogram. A referee's objection to that cross-check is fair and was
made: a slope through four survival points is a description of four points, it carries no
interval of its own, and quoting it beside a fitted value invites the reader to treat two
descriptions as one confirmation.

This module replaces the eyeballed slope with two estimators that state their own
uncertainty, both computed from the same committed `bpftrace` histograms:

  binned_pareto_mle()   The grouped-data maximum likelihood estimate for a Pareto tail.
                        `bpftrace` reports log2 buckets, so the sample is interval-censored
                        and the individual order statistics a classical Hill estimator needs
                        do not exist. The multinomial likelihood over the buckets is the
                        right object: conditional on landing in the window, the probability
                        of bucket [a,b) is (a^-alpha - b^-alpha)/(lo^-alpha - hi^-alpha).
                        The interval is a profile-likelihood interval, not a Wald interval,
                        because the log-likelihood is visibly asymmetric in alpha at these
                        counts and a symmetric interval would misreport the lower end.

  exceedance_index()    The two-point estimator on the exact counters bpftrace keeps
                        alongside the histogram (@over_500us and friends). Those counters
                        are not bucketed, so this estimate is free of any binning
                        assumption; the nested counts give a conditional binomial, and a
                        Wilson interval on the retention ratio maps monotonically onto an
                        interval for alpha.

The two disagree, and the disagreement is the finding: a single index does not describe this
distribution across the decade, which is why the manuscript now reports the window it was
measured on rather than a constant of the machine.

CLI:
    python scripts/tail_index_traced.py            # every traced histogram in the tree
    python scripts/tail_index_traced.py --json     # machine-readable, for the emitter
"""
import argparse
import glob
import json
import math
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stat_intervals import wilson  # noqa: E402

RESULTS = os.path.join("docs", "results")

# Chi-square 95% quantile at 1 df, halved: the profile-likelihood drop for a 95% interval.
# 3.841459 / 2. Tabulated rather than imported for the reason stat_intervals tabulates t.
PROFILE_DROP = 1.9207295

# The window the manuscript quotes, in microseconds. 0.25-2 ms is where the payload sweep
# put T_true, so it is the region the application-level rate actually samples; outside it
# the index is a different number and the manuscript says so.
WINDOW_LO_US = 256
WINDOW_HI_US = 2048

# Above the mode the survival is a different object; the manuscript reports it separately
# rather than folding it into a single index that describes neither region.
TAIL_LO_US = 4096

_SUFFIX = {"": 1, "K": 1024, "M": 1024 * 1024, "G": 1024 * 1024 * 1024}
_BIN_RE = re.compile(r"^\[(\d+)([KMG]?)(?:,\s*(\d+)([KMG]?)\))?\]?\s+(\d+)")
_COUNTER_RE = re.compile(r"^@(over_(\d+)us|count):\s*(\d+)")


def _scale(value, suffix):
    return int(value) * _SUFFIX[suffix]


def parse_runqlat(text):
    """Parse one bpftrace runqlat dump.

    Returns (bins, counters) where bins is [(lo_us, hi_us, count), ...] with hi exclusive,
    and counters maps the exact-counter names to their values. A single-value bucket such
    as "[1]" is returned as [1, 2), which is what a log2 histogram means by it.
    """
    bins, counters = [], {}
    for line in text.splitlines():
        line = line.strip()
        m = _COUNTER_RE.match(line)
        if m:
            counters[m.group(1)] = int(m.group(3))
            continue
        m = _BIN_RE.match(line)
        if not m:
            continue
        lo = _scale(m.group(1), m.group(2))
        hi = _scale(m.group(3), m.group(4)) if m.group(3) is not None else lo * 2
        bins.append((lo, hi, int(m.group(5))))
    return bins, counters


def window(bins, lo_us=WINDOW_LO_US, hi_us=WINDOW_HI_US):
    """The buckets wholly inside [lo_us, hi_us). Partial buckets are dropped, not split.

    Splitting a log2 bucket would require assuming a within-bucket density, which is the
    very thing being estimated. Dropping is the honest choice and it costs nothing here
    because the window is chosen on bucket boundaries.
    """
    return [b for b in bins if b[0] >= lo_us and b[1] <= hi_us]


def _loglik(alpha, bins):
    """Multinomial log-likelihood of the bucket counts under a Pareto tail, conditioned
    on the observation lying in the window."""
    lo, hi = bins[0][0], bins[-1][1]
    norm = lo ** -alpha - hi ** -alpha
    if norm <= 0:
        return -math.inf
    total = 0.0
    for a, b, n in bins:
        if not n:
            continue
        mass = a ** -alpha - b ** -alpha
        if mass <= 0:
            return -math.inf
        total += n * math.log(mass / norm)
    return total


def _maximise(bins, lo=1e-4, hi=8.0, tol=1e-9):
    """Golden-section maximisation of the log-likelihood on [lo, hi]."""
    phi = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = lo, hi
    c, d = b - phi * (b - a), a + phi * (b - a)
    fc, fd = _loglik(c, bins), _loglik(d, bins)
    while b - a > tol:
        if fc > fd:
            b, d, fd = d, c, fc
            c = b - phi * (b - a)
            fc = _loglik(c, bins)
        else:
            a, c, fc = c, d, fd
            d = a + phi * (b - a)
            fd = _loglik(d, bins)
    return (a + b) / 2.0


def _root(bins, target, lo, hi, tol=1e-9):
    """Bisect for the alpha where the log-likelihood crosses `target` between lo and hi."""
    flo = _loglik(lo, bins) - target
    fhi = _loglik(hi, bins) - target
    if flo * fhi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2.0
        fmid = _loglik(mid, bins) - target
        if abs(fmid) < tol or hi - lo < tol:
            return mid
        if flo * fmid <= 0:
            hi, fhi = mid, fmid
        else:
            lo, flo = mid, fmid
    return (lo + hi) / 2.0


def binned_pareto_mle(bins):
    """Grouped-data MLE for the Pareto index over the given buckets.

    Returns (alpha, lo, hi, n) with a profile-likelihood 95% interval. Raises ValueError
    if the buckets carry no counts, because an index estimated from nothing is the kind of
    number this project exists to refuse.
    """
    bins = [b for b in bins if b[2] > 0]
    if len(bins) < 2:
        raise ValueError("need at least two populated buckets to estimate an index")
    n = sum(b[2] for b in bins)
    alpha = _maximise(bins)
    target = _loglik(alpha, bins) - PROFILE_DROP
    lo = _root(bins, target, 1e-4, alpha)
    hi = _root(bins, target, alpha, 12.0)
    return alpha, lo, hi, n


def exceedance_index(n_lo, n_hi, x_lo, x_hi):
    """Two-point tail index from nested exceedance counts, with a Wilson-derived interval.

    n_lo counts events above x_lo, n_hi those above x_hi > x_lo, so the second set is
    contained in the first and n_hi | n_lo is binomial. Under S(x) = C x^-alpha the ratio
    is (x_hi/x_lo)^-alpha, so alpha = -ln(p) / ln(x_hi/x_lo), decreasing in p: the Wilson
    bounds map across with their ends exchanged.
    """
    if not 0 < n_hi <= n_lo:
        raise ValueError("exceedance counts must be nested and positive")
    if x_hi <= x_lo:
        raise ValueError("x_hi must exceed x_lo")
    ratio = math.log(x_hi / x_lo)
    p_lo, p_hi = wilson(n_hi, n_lo)
    alpha = -math.log(n_hi / n_lo) / ratio
    hi = -math.log(p_lo) / ratio if p_lo > 0 else float("inf")
    lo = -math.log(p_hi) / ratio if p_hi > 0 else float("inf")
    return alpha, lo, hi


def octave_indices(bins):
    """The index implied by each adjacent pair of buckets, as [(lo_us, alpha), ...].

    A power law over the window would return the same value for every octave. This is the
    cheapest possible check that the model holds, and it is the check the manuscript's
    earlier "windowed log-log index" skipped: a least-squares slope through four survival
    points returns a number whether or not the points lie on a line, and here they do not.

    For two log2 buckets of equal width ratio the mass ratio is (b_lo/a_lo)^alpha, so the
    estimate is a division and a logarithm with no fitting in it at all.

    Empty buckets are removed before pairing rather than skipped in place: a single zero
    count between two populated buckets would otherwise discard both estimates that
    straddle it, when what it actually permits is one estimate over the wider span.
    """
    populated = [b for b in bins if b[2] > 0]
    out = []
    for (a_lo, _, a_n), (b_lo, _, b_n) in zip(populated, populated[1:]):
        span = math.log(b_lo / a_lo)
        if span <= 0:
            continue
        out.append((a_lo, math.log(a_n / b_n) / span))
    return out


def modes(bins):
    """Local maxima of the bucket counts, as [(lo_us, count, share, ratio_to_lower), ...].

    A power law is monotone decreasing, so any interior local maximum falsifies it before
    any index is estimated. This is the check that turns "the two estimators disagree" into
    "the distribution has a mode there", which is a statement about the machine rather than
    about the estimators.
    """
    total = sum(b[2] for b in bins) or 1
    out = []
    for i in range(1, len(bins) - 1):
        lo, _, n = bins[i]
        if n > bins[i - 1][2] and n > bins[i + 1][2]:
            below = bins[i - 1][2]
            out.append((lo, n, n / total, (n / below) if below else float("inf")))
    return out


def _fitted_cdf(alpha, edges):
    lo, hi = edges[0], edges[-1]
    norm = lo ** -alpha - hi ** -alpha
    return [(lo ** -alpha - e ** -alpha) / norm for e in edges]


def binned_ks(bins, alpha):
    """Kolmogorov-Smirnov distance between the bucket counts and the fitted tail.

    Evaluated at the bucket edges, which is where an interval-censored sample supports a
    CDF comparison at all.
    """
    edges = [b[0] for b in bins] + [bins[-1][1]]
    n = sum(b[2] for b in bins)
    fit = _fitted_cdf(alpha, edges)
    emp, cum = [0.0], 0
    for _, _, c in bins:
        cum += c
        emp.append(cum / n)
    return max(abs(e - f) for e, f in zip(emp, fit))


def _binomial(rng, n, p):
    """One binomial draw. Exact where the interpreter offers it, normal-approximate above
    the regime where that matters, Bernoulli below it."""
    if p <= 0 or n <= 0:
        return 0
    if p >= 1:
        return n
    exact = getattr(rng, "binomialvariate", None)
    if exact is not None:
        return exact(n, p)
    if n * p > 30:  # pragma: no cover - only on interpreters without binomialvariate
        k = int(round(rng.gauss(n * p, math.sqrt(n * p * (1 - p)))))
        return max(0, min(n, k))
    return sum(1 for _ in range(n)  # pragma: no cover - no binomialvariate here
               if rng.random() < p)


def _multinomial(rng, n, probs):
    """Conditional-binomial multinomial draw, so a bootstrap replicate costs one draw per
    bucket rather than one per observation."""
    out, left, remaining = [], n, 1.0
    for p in probs[:-1]:
        k = _binomial(rng, left, min(1.0, p / remaining)) if remaining > 0 else 0
        out.append(k)
        left -= k
        remaining -= p
    out.append(left)
    return out


def gof_pvalue(bins, n_boot=2500, seed=20260819):
    """Semi-parametric bootstrap goodness of fit for the binned power law.

    Two estimators disagreeing is evidence that a model is wrong, but it is not a test. This
    is the test the binned-power-law literature uses: fit, measure the KS distance, then draw
    replicates *from the fitted model*, refit each, and ask how often the fitted model
    produces a fit at least as bad as the one observed. A small p rejects the power law.

    Returns (d_observed, p_value, alpha, n_boot_used).
    """
    alpha, _, _, n = binned_pareto_mle(bins)
    d_obs = binned_ks(bins, alpha)
    edges = [b[0] for b in bins] + [bins[-1][1]]
    fit = _fitted_cdf(alpha, edges)
    probs = [fit[i + 1] - fit[i] for i in range(len(bins))]
    rng = random.Random(seed)
    worse, used = 0, 0
    for _ in range(n_boot):
        counts = _multinomial(rng, n, probs)
        synth = [(bins[i][0], bins[i][1], counts[i]) for i in range(len(bins))]
        try:
            a_s, _, _, _ = binned_pareto_mle(synth)
        except ValueError:  # pragma: no cover - a replicate with one populated bucket
            continue
        used += 1
        if binned_ks(synth, a_s) >= d_obs:
            worse += 1
    return d_obs, (worse / used if used else float("nan")), alpha, used


def traced_histograms(root=RESULTS):
    """Every committed runqlat dump, as (tag, path), sorted for a stable report."""
    pattern = os.path.join(root, "depth", "*", "*", "runqlat.txt")
    out = []
    for path in sorted(glob.glob(pattern)):
        parts = path.replace("\\", "/").split("/")
        out.append(("%s/%s" % (parts[-3], parts[-2]), path))
    return out


def estimate(path):
    """Both estimators for one dump, as a plain dict."""
    with open(path, encoding="utf-8") as fh:
        bins, counters = parse_runqlat(fh.read())
    win = window(bins)
    alpha, lo, hi, n = binned_pareto_mle(win)
    out = {
        "path": path.replace("\\", "/"),
        "window_lo_us": WINDOW_LO_US,
        "window_hi_us": WINDOW_HI_US,
        "mle_alpha": alpha,
        "mle_lo": lo,
        "mle_hi": hi,
        "mle_n": n,
        "traced_events": counters.get("count"),
        "octaves": octave_indices(win),
        "modes": modes(bins),
    }
    above = [b for b in bins if b[0] >= TAIL_LO_US]
    if len(above) >= 2:
        a, alo, ahi, an = binned_pareto_mle(above)
        out.update({"tail_alpha": a, "tail_lo": alo, "tail_hi": ahi, "tail_n": an,
                    "tail_from_us": TAIL_LO_US})
    d, pval, _, used = gof_pvalue(win)
    out.update({"gof_d": d, "gof_p": pval, "gof_boot": used})
    if "over_500us" in counters and "over_2000us" in counters:
        ex, exlo, exhi = exceedance_index(counters["over_500us"], counters["over_2000us"],
                                          500.0, 2000.0)
        out.update({"exc_alpha": ex, "exc_lo": exlo, "exc_hi": exhi,
                    "exc_n_lo": counters["over_500us"], "exc_n_hi": counters["over_2000us"]})
    return out


def report(root=RESULTS):
    rows = []
    for tag, path in traced_histograms(root):
        try:
            est = estimate(path)
        except (OSError, ValueError):
            continue
        est["tag"] = tag
        rows.append(est)
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="Tail index from the traced run-queue histogram")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    ap.add_argument("--root", default=RESULTS)
    args = ap.parse_args(argv)
    rows = report(args.root)
    if not rows:
        print("no traced histograms found under %s" % args.root)
        return 1
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    for r in rows:
        print("%-18s window %d-%d us, n=%d of %s traced"
              % (r["tag"], r["window_lo_us"], r["window_hi_us"], r["mle_n"],
                 r["traced_events"]))
        print("    grouped Pareto MLE  alpha = %.3f  [%.3f, %.3f]  (profile likelihood)"
              % (r["mle_alpha"], r["mle_lo"], r["mle_hi"]))
        if "exc_alpha" in r:
            print("    exceedance 0.5-2 ms alpha = %.3f  [%.3f, %.3f]  (%d of %d)"
                  % (r["exc_alpha"], r["exc_lo"], r["exc_hi"], r["exc_n_hi"], r["exc_n_lo"]))
        print("    per-octave          %s"
              % ", ".join("%d us: %.2f" % (lo, a) for lo, a in r["octaves"]))
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
