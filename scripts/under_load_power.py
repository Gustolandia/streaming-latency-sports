#!/usr/bin/env python3
"""
under_load_power.py -- the rounds rule for freeze 42's block U (docs/results/under_load/DESIGN.md):
how often four rounds would confirm U-a's growth clause, U-b and U-c, simulated at the spreads the
runs read before the design showed.

The inputs are per-run 99th percentiles, in microseconds, of the consumer's turnaround (Tc), the
kernel-timed latency (W) and the thread-free latency (F), from two sets of runs on the second x86
pair, both read after their own verdicts and before this design was written:

  idle   block L's idle runs at 500 and 2,000 messages a second (freeze 41), and at 2,000 the
         idle run of freeze 41's pilot beside them;
  load   freeze 41's pilot runs under load at 2,000 (lp2000) and 500 (lp500l88), with 88% asked
         and 80.0-85.7% held, never judged.

Their acknowledgments were rebuilt from the producer's capture, since those runs kept no producer
journal, with scripts/so_journal.py's own parsers; on block K, which kept both, the two agree to the
nanosecond.

Those readings counted the turnaround as an earlier script did, over every command on the
consumer's connection and the whole run; the registered reader counts the requests for messages
sent while the measured messages were in flight. Loaded values move by about 1%, idle ones by up
to about 40 us, and the power hangs on the loaded excess.

A made-up block draws each run's value from a lognormal with the input's mean and its spread (a
coefficient of variation of at least IDLE_CV idle and LOAD_CV under load), takes a setup's value as
the median over its rounds, and judges the three clauses as the design states them, each in all
four cells at once, as the judge confirms a prediction. The load's excess over idle can be scaled,
to ask how the rule fares if the block's effect is smaller than the pilots'.

Plan version 46 (docs/results/under_load/DESIGN46.md) restates the rule from its own pilot, read
by scripts/under_load.py, before any judged run. With --pilot-table the inputs are that pilot's
runs; U-c is the share version 46 judges, from the means over each run's own top 1% of W_so, a
setup's value the mean over its rounds; U-a's real-time clause and U-d are simulated beside the
rest; and U-c is counted as the judge counts it, over the cells where U-b holds. A clause whose
pilot effect does not clear its margin in every cell cannot be brought to the bar by more rounds,
and is reported at the rounds the others need.

CLI:
    python scripts/under_load_power.py [--rounds 4] [--blocks 20000] [--seed 20261022]
    python scripts/under_load_power.py --pilot-table CSV [--rounds 4] [--most 12] [--blocks N]
"""
import argparse
import csv
import math
import random
import statistics
import sys

#: (broker, rate) -> {statistic: (idle runs, loaded runs)}.
INPUTS = {
    ("kafka", 2000): {"Tc": ((638, 790, 806, 607, 594), (5228, 5324)),
                      "W": ((1612, 1968, 2089, 1517, 1730), (5709, 7077)),
                      "F": ((1168, 1522, 1582, 1055, 1285), (1251, 1314))},
    ("redis", 2000): {"Tc": ((261, 291, 261, 260, 280), (3824, 4056)),
                      "W": ((1513, 2295, 1748, 1634, 1938), (5033, 7077)),
                      "F": ((1292, 1829, 1343, 1336, 1529), (2110, 3147))},
    ("kafka", 500): {"Tc": ((527, 515, 489, 512), (4407, 4798, 4420)),
                     "W": ((908, 756, 977, 610), (4309, 4446, 4091)),
                     "F": ((908, 756, 977, 610), (1171, 1250, 1135))},
    ("redis", 500): {"Tc": ((209, 213, 206, 213), (3536,)),
                     "W": ((557, 811, 577, 653), (3595,)),
                     "F": ((557, 811, 577, 653), (1449,))},
}

#: The least spread a made-up setup is given, idle and under load: an input of one or two runs
#: says little about its own spread.
IDLE_CV = 0.15
LOAD_CV = 0.25

#: The design's margins, as scripts/under_load.py judges them.
GROWTH = 1.5
HALF = 0.5

#: The rule's bar (D4-2): a prediction is run at the rounds that confirm it in this share of
#: made-up blocks under the law it states.
POWER = 0.8


def mean_and_cv(values, floor):
    """The mean of `values` and their coefficient of variation, at least `floor`."""
    m = statistics.fmean(values)
    cv = statistics.pstdev(values) / m if len(values) > 1 else 0.0
    return m, max(cv, floor)


def draw(rng, mean, cv):
    """One run's value from the lognormal with this mean and coefficient of variation."""
    s = math.sqrt(math.log(1.0 + cv * cv))
    return rng.lognormvariate(math.log(mean) - s * s / 2.0, s)


def setup_value(rng, mean, cv, rounds):
    return statistics.median(draw(rng, mean, cv) for _ in range(rounds))


def parameters(inputs, scale):
    """{statistic: (idle mean, idle cv, loaded mean, loaded cv)}, the load's excess over idle
    multiplied by `scale`."""
    out = {}
    for name, (idle, loaded) in inputs.items():
        mi, ci = mean_and_cv(idle, IDLE_CV)
        ml, cl = mean_and_cv(loaded, LOAD_CV)
        out[name] = (mi, ci, mi + scale * (ml - mi), cl)
    return out


def one_block(rng, par, rounds):
    """(U-a's growth clause, U-b, U-c) for one made-up block of one broker at one rate."""
    v = {k: (setup_value(rng, p[0], p[1], rounds), setup_value(rng, p[2], p[3], rounds))
         for k, p in par.items()}
    grew = v["Tc"][1] >= GROWTH * v["Tc"][0]
    gave_way = v["W"][1] >= GROWTH * v["W"][0]
    rise = v["W"][1] - v["W"][0]
    removed = rise > 0 and 1.0 - (v["F"][1] - v["F"][0]) / rise >= HALF
    return grew, gave_way, removed


def power(inputs, rounds, blocks, scale, seed):
    """{clause: share of `blocks` made-up blocks that confirm it}, for one broker at one rate."""
    rng = random.Random(seed)
    par = parameters(inputs, scale)
    counts = [0, 0, 0]
    for _ in range(blocks):
        for i, held in enumerate(one_block(rng, par, rounds)):
            counts[i] += held
    return dict(zip(("U-a", "U-b", "U-c"), (c / float(blocks) for c in counts)))


def table(rounds, blocks, seed, scales=(1.0, 0.5)):
    """[(scale, broker, rate, {clause: power})] for every cell the predictions judge."""
    rows = []
    for scale in scales:
        for (broker, rate), inputs in sorted(INPUTS.items()):
            rows.append((scale, broker, rate, power(inputs, rounds, blocks, scale, seed)))
    return rows


def joint_power(rounds, blocks, scale, seed):
    """{clause: share of made-up blocks in which it holds in all four cells at once}: the judge
    confirms a prediction only where every cell it reaches holds, so this is the power that
    counts. The cells are drawn independently, each from its own inputs."""
    rng = random.Random(seed)
    cells = [parameters(INPUTS[key], scale) for key in sorted(INPUTS)]
    counts = [0, 0, 0]
    for _ in range(blocks):
        outcomes = [one_block(rng, par, rounds) for par in cells]
        for i in range(3):
            counts[i] += all(o[i] for o in outcomes)
    return dict(zip(("U-a", "U-b", "U-c"), (c / float(blocks) for c in counts)))


# --- plan version 46 --------------------------------------------------------------------------

#: The clauses version 46 simulates, in the order the design lists them.
CLAUSES = ("U-a growth", "U-a real-time", "U-b", "U-c", "U-d")

#: The rates whose cells the predictions judge.
UPPER_RATES = (500, 2000)


def _number(value):
    return None if value in (None, "", "None") else float(value)


def pilot_inputs(rows):
    """{(broker, rate): {statistic: per-run values}} from a pilot's runs table: the turnaround's and
    W_so's 99th percentiles idle, loaded and loaded at real-time priority ("Tc", "W"), and the
    means over each run's top 1% of W_so of W_so and of F idle and loaded ("Wt", "Ft"). A cell
    missing any of them is left out."""
    out = {}
    for broker in ("kafka", "redis"):
        for rate in UPPER_RATES:
            def runs(loaded, realtime):
                return [r for r in rows if r["backend"] == broker
                        and int(float(r["rate"])) == rate
                        and (int(float(r["load_pct"])) > 0) == loaded
                        and str(r["priority"]) == str(realtime)]
            sets = (runs(False, False), runs(True, False), runs(True, True))
            cell = {}
            for name, field, picked in (("Tc", "Tc_p99", sets), ("W", "W_p99", sets),
                                        ("Wt", "W_tail", sets[:2]), ("Ft", "F_tail", sets[:2])):
                cell[name] = tuple(tuple(v for v in (_number(r.get(field)) for r in chosen)
                                         if v is not None) for chosen in picked)
            if all(all(values) for values in cell.values()):
                out[(broker, rate)] = cell
    return out


def parameters46(cell, scale):
    """{statistic: [(mean, cv) idle, then each loaded setup's]}, each loaded setup's excess over
    idle multiplied by `scale`."""
    out = {}
    for name, sets in cell.items():
        mi, ci = mean_and_cv(sets[0], IDLE_CV)
        rest = []
        for values in sets[1:]:
            m, c = mean_and_cv(values, LOAD_CV)
            rest.append((mi + scale * (m - mi), c))
        out[name] = [(mi, ci)] + rest
    return out


def one_cell46(rng, par, rounds):
    """(U-a's growth clause, U-a's real-time clause, U-b, U-c, U-d) for one made-up block of one
    broker at one rate, U-c's share read whatever U-b says."""
    def median(p):
        return statistics.median(draw(rng, p[0], p[1]) for _ in range(rounds))

    def mean(p):
        return statistics.fmean(draw(rng, p[0], p[1]) for _ in range(rounds))
    tc = [median(p) for p in par["Tc"]]
    w = [median(p) for p in par["W"]]
    wt = [mean(p) for p in par["Wt"]]
    ft = [mean(p) for p in par["Ft"]]
    rise = wt[1] - wt[0]
    return (tc[1] >= GROWTH * tc[0], tc[2] <= HALF * tc[1], w[1] >= GROWTH * w[0],
            rise > 0 and 1.0 - (ft[1] - ft[0]) / rise >= HALF, w[2] <= HALF * w[1])


def verdicts46(outcomes):
    """{clause: confirmed} over the cells of one made-up block, as scripts/under_load.py judges:
    every cell for each clause, and U-c over the cells where U-b holds, if there are any."""
    out = {c: all(o[i] for o in outcomes) for i, c in enumerate(CLAUSES)}
    judged = [o for o in outcomes if o[2]]
    out["U-c"] = bool(judged) and all(o[3] for o in judged)
    return out


def joint_power46(inputs, rounds, blocks, scale, seed):
    """{clause: share of `blocks` made-up blocks that confirm it in every cell}."""
    rng = random.Random(seed)
    cells = [parameters46(inputs[key], scale) for key in sorted(inputs)]
    counts = dict.fromkeys(CLAUSES, 0)
    for _ in range(blocks):
        for clause, held in verdicts46([one_cell46(rng, par, rounds) for par in cells]).items():
            counts[clause] += held
    return {c: counts[c] / float(blocks) for c in CLAUSES}


def clears(inputs):
    """{clause: whether its pilot means clear its margin in every cell}."""
    out = dict.fromkeys(CLAUSES, bool(inputs))
    for cell in inputs.values():
        tc, w = ([statistics.fmean(v) for v in cell[k]] for k in ("Tc", "W"))
        wt, ft = ([statistics.fmean(v) for v in cell[k]] for k in ("Wt", "Ft"))
        rise = wt[1] - wt[0]
        found = (tc[1] >= GROWTH * tc[0], tc[2] <= HALF * tc[1], w[1] >= GROWTH * w[0],
                 rise > 0 and 1.0 - (ft[1] - ft[0]) / rise >= HALF, w[2] <= HALF * w[1])
        for clause, ok in zip(CLAUSES, found):
            out[clause] = out[clause] and ok
    return out


def rounds_needed(inputs, blocks, seed, start=4, most=12):
    """(rounds, {clause: power} there): the least rounds from `start` at which every clause whose
    pilot effect clears its margin is confirmed in at least POWER of made-up blocks at the pilot's
    effects; (None, the powers at `most`) where no number up to `most` does."""
    wanted = [c for c, ok in clears(inputs).items() if ok]
    p = {}
    for rounds in range(start, most + 1):
        p = joint_power46(inputs, rounds, blocks, 1.0, seed)
        if all(p[c] >= POWER for c in wanted):
            return rounds, p
    return None, p


def read_rows(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def main46(args):
    inputs = pilot_inputs(read_rows(args.pilot_table))
    print("cells with every input: %s" % ", ".join("%s %d" % k for k in sorted(inputs)))
    clear = clears(inputs)
    print("clears its margin at the pilot's means in every cell: %s" % ", ".join(
        "%s %s" % (c, "yes" if clear[c] else "no") for c in CLAUSES))
    for scale in (1.0, 0.5):
        p = joint_power46(inputs, args.rounds, args.blocks, scale, args.seed)
        print("%d rounds, excess %.2f: %s" % (args.rounds, scale, "  ".join(
            "%s %.3f" % (c, p[c]) for c in CLAUSES)))
    rounds, p = rounds_needed(inputs, args.blocks, args.seed, args.rounds, args.most)
    if rounds is None:
        print("no number of rounds up to %d brings every clause that clears its margin to %.2f"
              % (args.most, POWER))
    else:
        print("the rule asks %d rounds: %s" % (rounds, "  ".join(
            "%s %.3f" % (c, p[c]) for c in CLAUSES)))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--blocks", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=20261022)
    ap.add_argument("--pilot-table", default=None)
    ap.add_argument("--most", type=int, default=12)
    args = ap.parse_args(argv)
    if args.pilot_table:
        return main46(args)
    rows = table(args.rounds, args.blocks, args.seed)
    print("excess  broker  rate   U-a    U-b    U-c")
    for scale, broker, rate, p in rows:
        print("%5.2f   %-6s %5d  %.3f  %.3f  %.3f" % (scale, broker, rate, p["U-a"], p["U-b"],
                                                      p["U-c"]))
    joint = []
    for scale in (1.0, 0.5):
        p = joint_power(args.rounds, args.blocks, scale, args.seed)
        joint.append(min(p.values()))
        print("all four cells at once, excess %.2f: U-a %.3f  U-b %.3f  U-c %.3f"
              % (scale, p["U-a"], p["U-b"], p["U-c"]))
    least = min(joint)
    print("least %.3f against the rule's %.2f at %d rounds: %s"
          % (least, POWER, args.rounds, "enough" if least >= POWER else "not enough"))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
