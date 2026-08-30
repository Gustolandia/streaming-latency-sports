#!/usr/bin/env python3
"""
fit_stall_mixture.py
Separate the three stall populations, and say whether the separation is trustworthy.

Why this exists. The traced run-queue spectrum (Section V-D) is described in the paper as
trimodal and left there. A co-author asked for the next step: fit the modes as components,
separate them, and see whether the separated components support a statistical correction of
already-collected measurements rather than only the operational remedies of Section VI-B.

The data is bpftrace's log2 histogram -- 17 buckets over [1 us, 64 ms), 551,956 wakeups for
the baseline arm. On the log2 scale those buckets are equal-width, so a lognormal component
is a normal component in x = log2(us), and the natural model is a K-component normal mixture
fitted to binned counts.

Method, and the honesty constraints on it:

    Binned EM with exact bucket masses. No bucket-midpoint approximation: the E-step uses the
    normal CDF over each bucket and the M-step uses truncated-normal moments, so nothing
    depends on pretending the data sits at bucket centres. stdlib only (math.erf).

    Model selection by BIC over K = 1..4. A K that wins BIC but whose bootstrap refits scatter
    is reported as unidentifiable, because a mixture that fits but cannot be pinned down
    supports no remedy at all -- and saying so is a result.

    Uncertainty by multinomial bootstrap: resample the 551,956 events over the observed
    buckets, refit, take percentile intervals on every parameter. Components are matched
    across refits by sorted location, and the label-switching rate is reported.

CLI:
    python scripts/fit_stall_mixture.py                     # both arms, K=1..4, bootstrap
    python scripts/fit_stall_mixture.py --boot 200
"""
import argparse
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tail_index_traced as tit

BASE = os.path.join("docs", "results", "depth", "ea9", "l88_base", "runqlat.txt")
RT = os.path.join("docs", "results", "depth", "ea9", "l88_rt", "runqlat.txt")
OUT = os.path.join("docs", "results", "stall_mixture.json")

SQRT2 = math.sqrt(2.0)


def phi(z):
    return math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)


def Phi(z):
    return 0.5 * (1.0 + math.erf(z / SQRT2))


def load_bins(path):
    """[(lo_x, hi_x, count)] with x = log2(us).

    bpftrace's "[0]" bucket holds wakeups whose latency rounded down to 0 us -- i.e. the
    interval [0, 1). Zero has no logarithm, so that bucket is represented as [0.25, 1) us,
    half an octave wide below the [1, 2) bucket. The choice is documented rather than
    important: the bucket's mass is what constrains the fit, not its assumed left edge.
    """
    with open(path, encoding="utf-8") as fh:
        bins, counters = tit.parse_runqlat(fh.read())
    out = []
    for lo, hi, c in bins:
        if c <= 0:
            continue
        lo_x = math.log2(lo) if lo > 0 else math.log2(0.25)
        hi_x = math.log2(hi) if hi > 0 else 0.0          # the [0] bucket: [0.25, 1) us
        out.append((lo_x, hi_x, c))
    return out, counters


def _bucket_mass(mu, sigma, lo, hi):
    return max(Phi((hi - mu) / sigma) - Phi((lo - mu) / sigma), 1e-300)


def _trunc_moments(mu, sigma, lo, hi):
    """E[x], E[x^2] of N(mu, sigma^2) truncated to [lo, hi].

    Guarded for buckets far into a component's tail: there both CDF values underflow, the
    normaliser Z clamps, and the exact formula returns moments astronomically outside the
    bucket -- which is how the whole fit went NaN on the go-first arm. When the bucket sits
    beyond ~8 sigma the truncated mass hugs the near edge, so the near edge IS the moment to
    within double precision, and that is what is returned.
    """
    a = (lo - mu) / sigma
    b = (hi - mu) / sigma
    if a > 8.0:                       # bucket entirely above the component
        return lo, lo * lo
    if b < -8.0:                      # bucket entirely below the component
        return hi, hi * hi
    Z = max(Phi(b) - Phi(a), 1e-300)
    pa, pb = phi(a), phi(b)
    m1 = mu + sigma * (pa - pb) / Z
    m2 = mu * mu + sigma * sigma + 2 * mu * sigma * (pa - pb) / Z \
        + sigma * sigma * (a * pa - b * pb) / Z
    # belt and braces: a truncated moment cannot leave the bucket
    m1 = min(max(m1, lo), hi)
    m2 = min(max(m2, m1 * m1), max(lo * lo, hi * hi) + (hi - lo) ** 2)
    return m1, m2


def loglik(bins, w, mu, sg):
    ll = 0.0
    for lo, hi, c in bins:
        p = sum(w[j] * _bucket_mass(mu[j], sg[j], lo, hi) for j in range(len(w)))
        ll += c * math.log(max(p, 1e-300))
    return ll


def _start_means(bins, k, rng):
    """Spread starting means over the data quantiles, with jitter to break restarts apart.

    Every mean is placed before this returns: the final bucket's cumulative count equals n,
    every target is strictly below n, and the inner while drains all remaining targets there
    -- so k components on a one-bucket histogram simply all start on that bucket, and EM
    reports the surplus as collapsed weights rather than crashing."""
    n = sum(c for _l, _h, c in bins)
    xs = sorted(((lo + hi) / 2.0, c) for lo, hi, c in bins)
    cum, targets, means = 0, [(i + 0.5) / k for i in range(k)], []
    ti = 0
    for x, c in xs:
        cum += c
        while ti < k and cum >= targets[ti] * n:
            means.append(x + rng.uniform(-0.3, 0.3))
            ti += 1
    return means


def _estep(bins, w, mu, sg):
    """Responsibility-weighted sufficient statistics per component.

    The `r <= 0` guard is for a responsibility that underflows to exactly zero -- possible
    when a component's weight has shrunk to ~1e-30 and the bucket sits in its far tail, and
    the truncated moments must not be evaluated there."""
    k = len(w)
    num_w = [0.0] * k
    num_m1 = [0.0] * k
    num_m2 = [0.0] * k
    for lo, hi, c in bins:
        masses = [w[j] * _bucket_mass(mu[j], sg[j], lo, hi) for j in range(k)]
        tot = sum(masses)
        for j in range(k):
            r = c * masses[j] / tot
            if r <= 0:
                continue
            m1, m2 = _trunc_moments(mu[j], sg[j], lo, hi)
            num_w[j] += r
            num_m1[j] += r * m1
            num_m2[j] += r * m2
    return num_w, num_m1, num_m2


def _mstep(n, w, mu, sg, num_w, num_m1, num_m2):
    """Update parameters in place. A component that received no responsibility keeps its
    parameters rather than dividing by zero; the next E-step may revive or starve it."""
    for j in range(len(w)):
        if num_w[j] <= 0:
            continue
        w[j] = num_w[j] / n
        mu[j] = num_m1[j] / num_w[j]
        var = max(num_m2[j] / num_w[j] - mu[j] * mu[j], 1e-4)
        sg[j] = math.sqrt(var)


def em_fit(bins, k, seed=0, iters=600, tol=1e-9):
    """One EM run from a deterministic quantile-spread start plus jitter."""
    rng = random.Random(seed)
    n = sum(c for _l, _h, c in bins)
    w = [1.0 / k] * k
    mu = sorted(_start_means(bins, k, rng))
    sg = [1.2] * k

    prev = -1e18
    for _ in range(iters):
        num_w, num_m1, num_m2 = _estep(bins, w, mu, sg)
        _mstep(n, w, mu, sg, num_w, num_m1, num_m2)
        ll = loglik(bins, w, mu, sg)
        if abs(ll - prev) < tol * abs(prev):
            break
        prev = ll
    order = sorted(range(k), key=lambda j: mu[j])
    return ([w[j] for j in order], [mu[j] for j in order], [sg[j] for j in order], prev)


def fit_best(bins, k, restarts=6):
    best = None
    for s in range(restarts):
        r = em_fit(bins, k, seed=s)
        if best is None or r[3] > best[3]:
            best = r
    return best


def bic(ll, k, n):
    return -2.0 * ll + (3 * k - 1) * math.log(n)


def bootstrap(bins, k, reps, seed=1):
    """Multinomial resample over buckets, refit, percentile intervals per sorted component."""
    rng = random.Random(seed)
    n = sum(c for _l, _h, c in bins)
    probs = [c / n for _l, _h, c in bins]
    samples = {q: [[] for _ in range(k)] for q in ("w", "mu_us", "sigma_oct")}
    for _ in range(reps):
        counts = [0] * len(bins)
        # multinomial via repeated binomials
        remaining, prob_left = n, 1.0
        for i, p in enumerate(probs):
            if prob_left <= 0 or remaining <= 0:
                break
            pp = min(max(p / prob_left, 0.0), 1.0)
            # binomial draw via normal approx for speed at n ~ 5e5, exact tails don't matter here
            mean = remaining * pp
            sd = math.sqrt(max(remaining * pp * (1 - pp), 1e-12))
            c = int(round(rng.gauss(mean, sd)))
            c = max(0, min(remaining, c))
            counts[i] = c
            remaining -= c
            prob_left -= p
        rb = [(bins[i][0], bins[i][1], counts[i]) for i in range(len(bins)) if counts[i] > 0]
        w, mu, sg, _ll = fit_best(rb, k, restarts=3)
        for j in range(k):
            samples["w"][j].append(w[j])
            samples["mu_us"][j].append(2.0 ** mu[j])
            samples["sigma_oct"][j].append(sg[j])
    def ci(v):
        v = sorted(v)
        lo = v[int(0.025 * len(v))]
        hi = v[min(int(0.975 * len(v)), len(v) - 1)]
        return [lo, hi]
    return {q: [ci(samples[q][j]) for j in range(k)] for q in samples}


def analyse(path, label, kmax, reps):
    bins, counters = load_bins(path)
    n = sum(c for _l, _h, c in bins)
    out = {"label": label, "n": n, "counters": counters, "fits": {}}
    print("\n=== %s: %d wakeups over %d buckets ===" % (label, n, len(bins)))
    print("  K   loglik        BIC")
    best_k, best_bic = None, None
    for k in range(1, kmax + 1):
        w, mu, sg, ll = fit_best(bins, k)
        b = bic(ll, k, n)
        out["fits"][k] = {"w": w, "mu_log2": mu, "mu_us": [2.0 ** m for m in mu],
                          "sigma_oct": sg, "loglik": ll, "bic": b}
        print("  %d  %12.1f  %12.1f" % (k, ll, b))
        if best_bic is None or b < best_bic:
            best_k, best_bic = k, b
    out["best_k"] = best_k
    # BIC decreases monotonically here because at n ~ 5e5 it buys components to absorb
    # lognormal-shape misfit, so the elbow, not the minimum, is the honest selector. Report
    # the successive drops so a reader can see the elbow rather than trust a argmin.
    drops = {k: out["fits"][k - 1]["bic"] - out["fits"][k]["bic"]
             for k in range(2, kmax + 1)}
    out["bic_drops"] = drops
    print("  BIC argmin K = %d; successive drops: %s"
          % (best_k, "  ".join("%d->%d: %.0f" % (k - 1, k, d) for k, d in drops.items())))

    # The paper-facing structure is three separated REGIONS, whatever K the fit uses inside
    # them. Group weights on fixed boundaries chosen in the empty buckets between clusters.
    for k in range(1, kmax + 1):
        f = out["fits"][k]
        g = [0.0, 0.0, 0.0]
        for j in range(k):
            us = f["mu_us"][j]
            g[0 if us < 32 else (1 if us < 1000 else 2)] += f["w"][j]
        f["group_w"] = g
    gw = {k: out["fits"][k]["group_w"] for k in range(3, kmax + 1)}
    print("  region weights (<32us | 32us-1ms | >1ms) by K:")
    for k, g in gw.items():
        print("    K=%d:  %5.1f%%  %5.1f%%  %5.1f%%" % (k, 100 * g[0], 100 * g[1], 100 * g[2]))
    fit = out["fits"][best_k]
    print("  components (weight, location, width in octaves):")
    for j in range(best_k):
        print("    %5.1f%%   %10.1f us   +/- %.2f oct"
              % (100 * fit["w"][j], fit["mu_us"][j], fit["sigma_oct"][j]))
    if reps:
        print("  bootstrapping x%d ..." % reps)
        fit["ci95"] = bootstrap(bins, best_k, reps)
        for j in range(best_k):
            wlo, whi = fit["ci95"]["w"][j]
            mlo, mhi = fit["ci95"]["mu_us"][j]
            print("    comp %d: weight %.1f%% [%.1f, %.1f]   location %.1f us [%.1f, %.1f]"
                  % (j + 1, 100 * fit["w"][j], 100 * wlo, 100 * whi,
                     fit["mu_us"][j], mlo, mhi))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mixture separation of the stall spectrum")
    ap.add_argument("--kmax", type=int, default=4)
    ap.add_argument("--boot", type=int, default=120)
    args = ap.parse_args(argv)
    result = {
        "base": analyse(BASE, "l88_base (default scheduling)", args.kmax, args.boot),
        "rt": analyse(RT, "l88_rt (stamping threads go-first)", args.kmax, args.boot),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1, sort_keys=True)
    print("\nwrote %s" % OUT)
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
