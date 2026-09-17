#!/usr/bin/env python3
"""
delay_calibration.py -- how far the trip moves per millisecond of receiver-only delay, measured in
every session, and the delay each planned trip therefore needs.

Why this exists. Draft 2 of the experiment plan assumed that a delay added on the receiver's path
lengthens the trip by exactly that delay, and its check allowed 0.05 ms either way. The first
Azure pilot (15 September 2026) showed otherwise: 2.03 ms added lengthened Kafka's median trip by
1.80 ms and Redis's by 2.51 ms, with repeat runs agreeing within about 0.1 ms. Trips placed by
"delay = target minus baseline" would miss by up to half a millisecond, as much as the detail of
the cliff the law predicts. So every session measures the relation first, in block C0 of
law_design.py, and places its trips from the measurement (Draft 3, change D3-5).

What is read, per finished run of a C0 queue:
  x         the added delay actually measured: the receiver's ping round trip minus the host's
            (delay_measured.json, written by cloud/azure/campaign.sh), less the same difference
            in the queue's zero-delay runs. The setting is only the step's label.
  y         the run's median trip, and its "got it" median and 99th percentile (pilot_checks.py).

What is fitted and checked, per backend and load, as the plan fixed before the data:
  line          least squares of y on x, with a 95% interval for the slope from resampling whole
                rounds;
  lack of fit   an F test of the line against the per-step means. If the line fails it at 5%, the
                per-step medians joined by straight segments are used instead;
  gate          P5(a) no trip below zero; P5(b) the slope's 95% interval above 0.5, and the
                calibration known to within 0.3 ms at every step: its 95% interval there, from
                the scatter of the runs about the line, or within the steps for the segments,
                lies within 0.3 ms of it; and a longer delay always giving a longer trip, without
                which no trip can be placed. Version 5 of the plan held every run to 0.1 ms;
                freeze 02 changed that after the second x86 pair's runs scattered around its
                calibration with a standard deviation of 0.18 to 0.27 ms, which no number of
                rounds brings under 0.1 ms. How far each run and each step median lies from the
                calibration is still written out. When only the precision fails, two more rounds
                can mend it (needs-rounds), and the fit then reads both queues;
  got it        P5(c) at every step against zero delay, two one-sided tests at 90%: equivalent if
                the median shift lies within 0.10 ms and the p99 ratio within 10%. A median shift
                larger than a quarter of the added delay is a gross departure and fails the gate.
                A step not shown equivalent does not fail it: the session is then analysed with
                each run's own "got it" distribution.

The statistics are written out here, from the regularized incomplete beta function, so that the
same code runs on the driver without scipy.

CLI:
    python3 scripts/delay_calibration.py fit --queue runs/azure/queues/c0.csv --out cal.json
    python3 scripts/delay_calibration.py needs-rounds --calibration cal.json
    python3 scripts/delay_calibration.py fit --queue c0.csv --queue c0b.csv --out cal.json
    python3 scripts/delay_calibration.py place --calibration cal.json --backend kafka --load 75 \\
        --trip-ms 3.4
"""
import argparse
import json
import math
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pilot_checks  # noqa: E402
import run_queue  # noqa: E402

MIN_SLOPE = 0.5
#: P5(b) as freeze 02 has it: at every step, the calibration's 95% interval lies within this.
KNOWN_WITHIN_MS = 0.30
#: The one part of the gate that more rounds of the same session can mend.
PRECISION_ONLY = frozenset({"known_within_0_3_ms"})
GOTIT_MARGIN_MS = 0.10
P99_RATIO = (0.9, 1.1)
GROSS_SHARE = 0.25
LACK_OF_FIT_ALPHA = 0.05
RESAMPLES = 1000


# --- the distributions the tests need --------------------------------------------------------

def betainc(a, b, x):
    """I_x(a, b), the regularized incomplete beta function, by Lentz's continued fraction."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    if x > (a + 1.0) / (a + b + 2.0):
        return 1.0 - betainc(b, a, 1.0 - x)
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                     + a * math.log(x) + b * math.log1p(-x))
    tiny = 1e-300
    c, d = 1.0, 1.0 - (a + b) * x / (a + 1.0)
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h, m = d, 0
    while True:
        m += 1
        for num in (m * (b - m) * x / ((a + 2 * m - 1.0) * (a + 2 * m)),
                    -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1.0))):
            d = 1.0 + num * d
            d = 1.0 / (d if abs(d) > tiny else tiny)
            c = 1.0 + num / c
            c = c if abs(c) > tiny else tiny
            h *= d * c
        if abs(d * c - 1.0) < 1e-14 or m >= 500:
            return front * h / a


def f_pvalue(f, df1, df2):
    """P(F >= f) under an F distribution with df1 and df2 degrees of freedom."""
    if f <= 0.0:
        return 1.0
    return betainc(df2 / 2.0, df1 / 2.0, df2 / (df2 + df1 * f))


def t_cdf(t, df):
    """P(T <= t) under Student's t with df degrees of freedom."""
    tail = 0.5 * betainc(df / 2.0, 0.5, df / (df + t * t))
    return 1.0 - tail if t >= 0 else tail


def t_quantile(p, df):
    """The t below which a share p, above one half, of the distribution lies."""
    low, high = 0.0, 1000.0
    for _ in range(100):
        mid = (low + high) / 2.0
        if t_cdf(mid, df) < p:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


# --- the line, its interval, and the test of its shape ---------------------------------------

def ols(points):
    """(intercept, slope) of y on x by least squares, from (x, y) pairs."""
    if len({x for x, _ in points}) < 2:
        raise ValueError("a slope needs at least two different delays")
    mx = statistics.fmean(x for x, _ in points)
    my = statistics.fmean(y for _, y in points)
    sxx = sum((x - mx) ** 2 for x, _ in points)
    slope = sum((x - mx) * (y - my) for x, y in points) / sxx
    return my - slope * mx, slope


def slope_interval(runs, seed, resamples=RESAMPLES):
    """95% interval for the slope, resampling whole rounds so a round's shared conditions stay
    together. A round that measured fewer than two different delays cannot hold a slope and is
    left out."""
    by_round = {}
    for r in runs:
        by_round.setdefault(r["round"], []).append((r["x"], r["trip"]))
    rounds = sorted(k for k, pts in by_round.items() if len({x for x, _ in pts}) > 1)
    if not rounds:
        raise ValueError("no round measured two different delays")
    rng = random.Random(seed)
    slopes = sorted(ols([p for _ in rounds for p in by_round[rng.choice(rounds)]])[1]
                    for _ in range(resamples))
    return slopes[round(0.025 * (resamples - 1))], slopes[round(0.975 * (resamples - 1))]


def lack_of_fit(runs, intercept, slope):
    """F test of the line against the per-step means, or None with too few steps or repeats."""
    steps = {}
    for r in runs:
        steps.setdefault(r["step"], []).append(r["trip"])
    df_steps, df_repeats = len(steps) - 2, len(runs) - len(steps)
    if df_steps < 1 or df_repeats < 1:
        return None
    residual = sum((r["trip"] - intercept - slope * r["x"]) ** 2 for r in runs)
    pure = sum((y - statistics.fmean(ys)) ** 2 for ys in steps.values() for y in ys)
    shape = max(0.0, residual - pure)
    if pure == 0.0:
        return {"f": None, "df_steps": df_steps, "df_repeats": df_repeats,
                "p": 0.0 if shape > 0.0 else 1.0}
    f = (shape / df_steps) / (pure / df_repeats)
    return {"f": f, "df_steps": df_steps, "df_repeats": df_repeats,
            "p": f_pvalue(f, df_steps, df_repeats)}


def step_medians(runs):
    """[[median measured delay, median trip]] for each step, in order of the delay set."""
    steps = {}
    for r in runs:
        steps.setdefault(r["step"], []).append(r)
    return [[statistics.median(r["x"] for r in rs), statistics.median(r["trip"] for r in rs)]
            for _, rs in sorted(steps.items())]


def predict(entry, x):
    """The calibration's trip at measured delay x; segments are held flat beyond both ends."""
    if entry["model"] == "line":
        return entry["intercept_ms"] + entry["slope"] * x
    points = entry["steps"]
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


def halfwidths(runs, entry):
    """[[measured delay, 95% half-width]] of the calibration at each step; None where the runs
    are too few to say.

    Under the line, from the scatter of the runs about it. Under the segments, which are the step
    medians, from the scatter within the steps, pooled; a median of three or more runs is taken
    to be sqrt(pi/2) times less precise than their mean, as for a large normal sample, and a
    median of one or two runs is their mean.
    """
    n = len(runs)
    if entry["model"] == "line":
        df = n - 2
        if df < 1:
            return [[x, None] for x, _ in entry["steps"]]
        xs = [r["x"] for r in runs]
        mean_x = statistics.fmean(xs)
        sxx = sum((x - mean_x) ** 2 for x in xs)
        s = math.sqrt(sum((r["trip"] - entry["intercept_ms"] - entry["slope"] * r["x"]) ** 2
                          for r in runs) / df)
        t = t_quantile(0.975, df)
        return [[x, t * s * math.sqrt(1.0 / n + (x - mean_x) ** 2 / sxx)]
                for x, _ in entry["steps"]]
    # The segments are chosen only when the lack-of-fit test could be run, so the steps repeat.
    by_step = {}
    for r in runs:
        by_step.setdefault(r["step"], []).append(r["trip"])
    df = n - len(by_step)
    s = math.sqrt(sum((y - statistics.fmean(ys)) ** 2 for ys in by_step.values() for y in ys)
                  / df)
    t = t_quantile(0.975, df)
    return [[x, t * s * (1.0 if len(ys) <= 2 else math.sqrt(math.pi / 2)) / math.sqrt(len(ys))]
            for (x, _), (_, ys) in zip(entry["steps"], sorted(by_step.items()))]


def delay_for(entry, trip_ms):
    """The added delay that reaches trip_ms, or None where the calibration measured nothing:
    below the zero-delay trip, which no added delay reaches, or beyond the longest step."""
    points = entry["steps"]
    if entry["model"] == "line":
        delay = (trip_ms - entry["intercept_ms"]) / entry["slope"]
        return round(delay, 3) if 0.0 <= delay <= points[-1][0] else None
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if y0 <= trip_ms <= y1:
            return round(max(0.0, x0 + (x1 - x0) * (trip_ms - y0) / (y1 - y0)), 3)
    return None


# --- the "got it" delay ----------------------------------------------------------------------

def _difference(before, after, transform=float):
    """mean(after) - mean(before) with its Welch 90% interval; no interval without two runs on
    each side."""
    a, b = [transform(v) for v in before], [transform(v) for v in after]
    diff = statistics.fmean(b) - statistics.fmean(a)
    if len(a) < 2 or len(b) < 2:
        return diff, None
    va, vb = statistics.variance(a) / len(a), statistics.variance(b) / len(b)
    if va + vb == 0.0:
        return diff, [diff, diff]
    df = (va + vb) ** 2 / (va ** 2 / (len(a) - 1) + vb ** 2 / (len(b) - 1))
    half = t_quantile(0.95, df) * math.sqrt(va + vb)
    return diff, [diff - half, diff + half]


def gotit_checks(runs):
    """P5(c): the "got it" median and p99 at every step with a delay, against zero delay."""
    zero = [r for r in runs if r["step"] == 0.0 and r["gotit"] is not None]
    low, high = math.log(P99_RATIO[0]), math.log(P99_RATIO[1])
    checks = []
    for step in sorted({r["step"] for r in runs if r["step"] > 0.0}):
        here = [r for r in runs if r["step"] == step and r["gotit"] is not None]
        if not zero or not here:
            continue
        shift, ci = _difference([r["gotit"] for r in zero], [r["gotit"] for r in here])
        log_ratio, log_ci = _difference([r["p99"] for r in zero], [r["p99"] for r in here],
                                        math.log)
        added = statistics.median(r["x"] for r in here)
        checks.append({
            "step_ms": step, "added_ms": added,
            "median_shift_ms": shift, "median_ci90_ms": ci,
            "median_equivalent": (ci is not None and -GOTIT_MARGIN_MS < ci[0]
                                  and ci[1] < GOTIT_MARGIN_MS),
            "p99_ratio": math.exp(log_ratio),
            "p99_ratio_ci90": None if log_ci is None else [math.exp(v) for v in log_ci],
            "p99_equivalent": log_ci is not None and low < log_ci[0] and log_ci[1] < high,
            "gross": abs(shift) > GROSS_SHARE * abs(added),
        })
    return checks


# --- one calibration, and a session's ---------------------------------------------------------

def fit_entry(runs, seed):
    """The calibration for one backend at one load, with its gate."""
    intercept, slope = ols([(r["x"], r["trip"]) for r in runs])
    low, high = slope_interval(runs, seed)
    shape = lack_of_fit(runs, intercept, slope)
    steps = step_medians(runs)
    line_fails = shape is not None and shape["p"] < LACK_OF_FIT_ALPHA
    entry = {"runs": len(runs), "rounds": len({r["round"] for r in runs}),
             "intercept_ms": intercept, "slope": slope, "slope_ci95": [low, high],
             "lack_of_fit": shape, "steps": steps, "model": "segments" if line_fails else "line"}
    residuals = [r["trip"] - predict(entry, r["x"]) for r in runs]
    step_residuals = [y - predict(entry, x) for x, y in steps]
    widths = halfwidths(runs, entry)
    checks = gotit_checks(runs)
    zero_gotit = [r["gotit"] for r in runs if r["step"] == 0.0 and r["gotit"] is not None]
    gate = {
        "never_negative": sum(r["negative"] for r in runs) == 0,
        "slope_above_half": low > MIN_SLOPE,
        "known_within_0_3_ms": all(w is not None and w <= KNOWN_WITHIN_MS for _, w in widths),
        "longer_delay_longer_trip": all(b[0] > a[0] and b[1] > a[1]
                                        for a, b in zip(steps, steps[1:])),
        "no_gross_gotit_departure": not any(c["gross"] for c in checks),
    }
    gate["ok"] = all(gate.values())
    entry.update(residual_max_ms=max(abs(v) for v in residuals),
                 residual_sd_ms=statistics.pstdev(residuals), step_residuals_ms=step_residuals,
                 halfwidths_ms=widths,
                 halfwidth_max_ms=max((w for _, w in widths if w is not None), default=None),
                 gotit=checks, gate=gate,
                 # What each later run's own "got it" median is held against, run by run
                 # (run_integrity.py): the median over this session's zero-delay runs.
                 gotit_zero_median_ms=statistics.median(zero_gotit) if zero_gotit else None)
    return entry


def calibrate(runs, seed=1):
    """{backend: {load: calibration}} from every run of a finished C0 queue."""
    groups = {}
    for r in runs:
        groups.setdefault(r["backend"], {}).setdefault(r["load"], []).append(r)
    return {backend: {load: fit_entry(rs, seed) for load, rs in sorted(loads.items())}
            for backend, loads in sorted(groups.items())}


def needs_more_rounds(calibration):
    """True when the only part of the gate that any entry failed is its precision, which more
    rounds of the same session can mend."""
    failed = {k for loads in calibration.values() for e in loads.values()
              for k, v in e["gate"].items() if k != "ok" and not v}
    return bool(failed) and failed <= PRECISION_ONLY


def rows_of_queues(paths, read=run_queue.read_queue):
    """Every row of the queues. They must not share a round: a second stage carries on from the
    rounds of the first, and the slope's interval resamples whole rounds."""
    rows, owner = [], {}
    for path in paths:
        mine = read(path)
        for rnd in sorted({r["round"] for r in mine}):
            if rnd in owner:
                raise ValueError("%s and %s both hold round %s" % (owner[rnd], path, rnd))
            owner[rnd] = path
        rows += mine
    return rows


def read_delay_file(run_dir):
    """(host, receiver) median ping round trips the runner measured for one run."""
    with open(os.path.join(run_dir, "delay_measured.json"), encoding="utf-8") as fh:
        measured = json.load(fh)
    return measured["host_median_ms"], measured["receiver_median_ms"]


def runs_from_queue(rows, summarise, read_delay, warmup_s=30.0):
    """(runs, zero offset): what the calibration reads from each finished run of a C0 queue."""
    done = [row for row in rows if row["status"] == "done" and row["run_dir"]]
    if not done:
        raise ValueError("the queue has no finished calibration runs")
    runs = []
    for row in done:
        params = json.loads(row["params"])
        summary = summarise(row["run_dir"], warmup_s)
        host, receiver = read_delay(row["run_dir"])
        runs.append({"key": row["key"], "round": row["round"], "backend": params["backend"],
                     "load": str(params["load_pct"]), "step": float(params["delay_ms"]),
                     "path_ms": receiver - host, "trip": summary["trip_median_ms"],
                     "gotit": summary["gotit_median_ms"], "p99": summary["gotit_p99_ms"],
                     "negative": summary["trip_negative"]})
    zeros = [r["path_ms"] for r in runs if r["step"] == 0.0]
    if not zeros:
        raise ValueError("the queue has no finished zero-delay run to measure added delays "
                         "against")
    offset = statistics.median(zeros)
    for r in runs:
        r["x"] = r["path_ms"] - offset
    return runs, offset


def main(argv=None, out=None, summarise=pilot_checks.summarise, read_delay=read_delay_file):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="How far the trip moves per millisecond of delay")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("fit")
    p.add_argument("--queue", required=True, action="append",
                   help="a finished C0 queue; name the second stage's queue too, if it ran")
    p.add_argument("--out", required=True)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--warmup-s", type=float, default=30.0)
    p = sub.add_parser("place")
    p.add_argument("--calibration", required=True)
    p.add_argument("--backend", required=True)
    p.add_argument("--load", required=True)
    p.add_argument("--trip-ms", type=float, required=True)
    p = sub.add_parser("needs-rounds")
    p.add_argument("--calibration", required=True)
    args = ap.parse_args(argv)
    try:
        if args.command == "needs-rounds":
            with open(args.calibration, encoding="utf-8") as fh:
                more = needs_more_rounds(json.load(fh)["calibration"])
            print("more rounds can make the calibration precise enough" if more else
                  "more rounds would not change what the gate found", file=out)
            return 0 if more else 1
        if args.command == "place":
            with open(args.calibration, encoding="utf-8") as fh:
                entry = json.load(fh)["calibration"][args.backend][args.load]
            delay = delay_for(entry, args.trip_ms)
            print(json.dumps({"backend": args.backend, "load": args.load,
                              "trip_ms": args.trip_ms, "delay_ms": delay}, sort_keys=True),
                  file=out)
            return 0 if delay is not None else 1
        runs, offset = runs_from_queue(rows_of_queues(args.queue), summarise, read_delay,
                                       args.warmup_s)
        result = {"queues": args.queue, "seed": args.seed, "zero_offset_ms": offset,
                  "calibration": calibrate(runs, args.seed)}
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
        passed = True
        for backend, loads in result["calibration"].items():
            for load, e in loads.items():
                failed = [k for k, v in e["gate"].items() if not v and k != "ok"]
                known = e["halfwidth_max_ms"]
                print("%s at %s%%: trip = %.3f + %.3f x delay (95%% %.3f to %.3f), %s, known "
                      "within %s ms, %s"
                      % (backend, load, e["intercept_ms"], e["slope"], e["slope_ci95"][0],
                         e["slope_ci95"][1], e["model"],
                         "?" if known is None else "%.3f" % known,
                         "GATE FAILED: " + ", ".join(failed) if failed else "gate passed"),
                      file=out)
                passed = passed and not failed
        return 0 if passed else 1
    except (OSError, ValueError, KeyError) as exc:
        print("ERROR: %s" % exc, file=out)
        return 2


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
