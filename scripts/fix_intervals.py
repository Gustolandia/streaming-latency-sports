#!/usr/bin/env python3
"""
fix_intervals.py -- intervals for the kernel-timed latency's moves, and the socket module's cost.

Freezes 39 and 40 judged "held still" on point estimates: a setup's median of six runs' statistics,
compared between loads and between priorities, within a band fixed before the runs (10% at the
median, 25% at the 99th percentile). A claim of sameness needs the interval on the move inside the
band (writing standard C20; the ninth version's referees, A §8.5 and B S6). This resamples each
setup's runs with replacement, recomputes the move, and writes each comparison's 95% interval
beside its band.

The module's cost: freeze 39 read the kernel's timestamps from captures with no module in the
clients, and freeze 40 read them through the module, in the same design on the same pair, on other
days. The clients' own time, D - W at the median, and D's 99th percentile, set side by side give a
first estimate of what the module costs, drift between the days included, and so an upper bound.

CLI:
    python scripts/fix_intervals.py --f1 docs/results/full_fix/f1_runs.csv \
        --f2 docs/results/so_fix/f2_runs.csv --moves OUT.csv --cost OUT.csv
"""
import argparse
import csv
import random
import statistics

BACKENDS = ("kafka", "redis")
IDLE, BUSY = 0, 88
#: The bands the plans fixed (F-a/F-b, G-b/G-c).
BANDS = {"median": 0.10, "p99": 0.25}
RESAMPLES = 10000
SEED = 20261015
LEVEL = 0.95


def read(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def runs_of(rows, backend, load, priority, field):
    """Each run's statistic in one setup."""
    return [float(r[field]) for r in rows if r["backend"] == backend
            and int(float(r["load_pct"])) == load and r["priority"] == str(priority)
            and r.get(field) not in ("", None)]


def move(base, other):
    """|median(other) - median(base)| / median(base)."""
    b = statistics.median(base)
    return abs(statistics.median(other) - b) / b


def interval(base, other, rng, resamples=RESAMPLES, level=LEVEL):
    """The bootstrap percentile interval of the move, each setup's runs resampled on their own."""
    moves = sorted(move([rng.choice(base) for _ in base], [rng.choice(other) for _ in other])
                   for _ in range(resamples))
    lo = moves[int((1 - level) / 2 * resamples)]
    hi = moves[min(resamples - 1, int((1 + level) / 2 * resamples))]
    return lo, hi


def comparisons(rows, field):
    """[(name, base runs, other runs)]: between the loads at each priority and between the
    priorities at each load, on both brokers, as full_fix.held_still compares them."""
    out = []
    for b in BACKENDS:
        for p in (False, True):
            out.append(("%s, %s priority: idle against load" % (b, "real-time" if p else "normal"),
                        runs_of(rows, b, IDLE, p, field), runs_of(rows, b, BUSY, p, field)))
        for load in (IDLE, BUSY):
            out.append(("%s, %d%% load: normal against real-time" % (b, load),
                        runs_of(rows, b, load, False, field), runs_of(rows, b, load, True, field)))
    return out


def move_rows(rows, block, latency, seed=SEED, resamples=RESAMPLES):
    """One row per comparison and statistic: the move, its interval, and whether the interval
    lies inside the band."""
    rng = random.Random(seed)
    out = []
    for stat, band in sorted(BANDS.items()):
        for name, base, other in comparisons(rows, "%s_%s" % (latency, stat)):
            if not base or not other:
                continue
            lo, hi = interval(base, other, rng, resamples)
            out.append({"block": block, "latency": latency, "statistic": stat,
                        "comparison": name, "move": move(base, other), "lo": lo, "hi": hi,
                        "band": band, "point_inside": move(base, other) <= band,
                        "interval_inside": hi <= band})
    return out


def client_time(rows, b, load, p):
    """The median over a setup's runs of each run's median D less its median W, both W from the
    captures, so that the two blocks are timed alike; None if the setup has no run."""
    found = [float(r["D_median"]) - float(r["W_median"]) for r in rows
             if r["backend"] == b and int(float(r["load_pct"])) == load
             and r["priority"] == str(p) and r.get("D_median") and r.get("W_median")]
    return statistics.median(found) if found else None


def cost_rows(f1, f2):
    """Per setup: the clients' own time, D - W, and D's 99th percentile, without the module (freeze
    39) and with it (freeze 40), in microseconds. 15 Oct 2026: each run's D - W first, then the
    median over runs, the estimator a referee recomputed; the blocks ran on different days, so the
    change holds the day's drift too."""
    out = []
    for b in BACKENDS:
        for load in (IDLE, BUSY):
            for p in (False, True):
                c1, c2 = client_time(f1, b, load, p), client_time(f2, b, load, p)
                if None in (c1, c2):
                    continue
                p99 = [statistics.median(runs_of(rows, b, load, p, "D_p99")) for rows in (f1, f2)]
                out.append({"backend": b, "load_pct": load, "priority": p,
                            "client_without": c1, "client_with": c2, "client_change": c2 - c1,
                            "D_p99_without": p99[0], "D_p99_with": p99[1]})
    return out


def write(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--f1", required=True)
    ap.add_argument("--f2", required=True)
    ap.add_argument("--moves", required=True)
    ap.add_argument("--cost", required=True)
    ap.add_argument("--resamples", type=int, default=RESAMPLES)
    args = ap.parse_args(argv)
    f1, f2 = read(args.f1), read(args.f2)
    moves = (move_rows(f1, "F1", "W", resamples=args.resamples)
             + move_rows(f2, "F2", "Wso", resamples=args.resamples))
    write(args.moves, moves)
    write(args.cost, cost_rows(f1, f2))
    worst = max(moves, key=lambda r: r["hi"] / r["band"])
    print("OK %d comparisons; the widest against its band: %s %s %s, move %.3f [%.3f, %.3f]"
          % (len(moves), worst["block"], worst["statistic"], worst["comparison"], worst["move"],
             worst["lo"], worst["hi"]))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
