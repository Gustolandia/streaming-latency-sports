#!/usr/bin/env python3
"""
a9_decompose.py -- why A9-2 predicts six to ten times too few negative readings where A9-2b comes
close, what A9's recording did to the rate it recorded, and how A9's recording and A6's histogram
see the same waits. Read on 28 September 2026, after the final judging (D32-1). It decides
nothing: A9 and P6 were answered by helper_waits.py, frozen, and stay as they were.

The two predictions, for a run whose stamping thread waited W_1 ... W_N for a CPU over a window of
length D, with margin m = T - g (its median trip less its median got-it):

  A9-2   sum over the waits of max(0, W_i - m), over D. Written out,
             A9-2 = (N / D) * P_w(W > m) * e(m),
         the waits a millisecond (lambda = N / D), the share of them that outlast m, and by how
         much on average they do (e(m), the mean excess); exactly so where one thread stamps.
  A9-2b  the share of the run's acknowledgements whose own wait outlasted m: P_ack(W > m).

So A9-2 / A9-2b = lambda * e(m) * P_w / P_ack. The first two make a number of waits a
millisecond times milliseconds -- the share of time spent in the part of a wait past the margin --
and the last compares a wait picked at random with the wait an acknowledgement meets. Both are
below one here, and their product is the under-prediction.

The recording's own effect. A9 records every python3 thread's scheduling events in a random half
of its runs; each setup's recorded runs are set against its unrecorded ones.

The two recordings. A6's histogram (runqlat.txt, A1's and A3's recorded runs) counts every wait of
every python3 thread after a wake-up or a preemption, with no clock and no thread. A9's events give
the same waits one by one, split by what began them: a wake-up (W then R) or a preemption (P then
R). Per run, the count of each and the share over 1 ms; per part, the waits over a quarter of a
millisecond counted in bins, and their density in the band from the 3 ms slice to a tick past it
over their density between 1 ms and the slice -- about 1 for waits spread evenly below the slice,
more where they pile up at it.

The waits themselves (A9-3, read in full). Every acknowledgement's own wait for a CPU, as A9-2b
reads it, pooled by pair, backend and load, and the share of them longer than x, S(x), every
quarter of a millisecond to 5 ms, set against the two shapes the wait could have at A9's 3 ms
slice s and 1 ms tick h, each given the one scale p that brings p F(x) nearest S(x):

  whole slice       the helper waits out a whole slice and then up to a tick, W = s + U: F(x) = 1
                    to the slice, straight down across the tick -- the plan's plateau and cliff;
  rest of a slice   it waits out the rest of the slice another task is running and then up to a
                    tick, W = R + U, R ~ U(0, s), U ~ U(0, h): cliff_shape.residual_rate.

Of the acknowledgements that waited more than 1 ms, the first keeps every one past 3 ms and the
second a fifth (F(3)/F(1) = 1 and 0.2).

CLI:
    python scripts/a9_decompose.py --a9 <campaign folder> [...] --a6 <campaign folder> [...]
                                   [--out <folder>]
"""
import argparse
import bisect
import csv
import json
import math
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cliff_shape  # noqa: E402
import helper_waits  # noqa: E402

#: The wait A6's histogram and A9's events are compared over, in ms.
LONG_MS = 1.0
#: The slice and tick every A9 campaign ran at, in ms, and the waits S(x) is read at.
A9_SLICE_MS, A9_TICK_MS = 3.0, 1.0
AT_MS = tuple(0.25 * k for k in range(1, 21))
#: The two shapes an acknowledgement's own wait could have, as the share of waits outlasting x.
WAIT_SHAPES = {"whole slice": cliff_shape.plan_rate,
               "rest of a slice": cliff_shape.residual_rate}
#: The (low, high] bins, in ms, every python3 thread's waits are counted in by what began them.
BAND_EDGES = (0.25, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 8.0)


# --- one A9 run ------------------------------------------------------------------------------------

def window_ms(run_dir):
    """The measured window's length in ms on the tracer's clock, as helper_waits reads it."""
    records = helper_waits.thread_records(run_dir)
    sent = helper_waits.messages(run_dir)
    producer = helper_waits.to_monotonic(records["producer"])
    return (producer(max(s for s, _, _ in sent)) - producer(min(s for s, _, _ in sent))) / 1e6


def decompose(run):
    """{a9_2, a9_2b, waits_per_ms, share_over, mean_excess_ms, product} for one recorded A9 run,
    or None where helper_waits does not read it."""
    found, _ = helper_waits.a9_run(run)
    if found is None or found["stamping_threads"] != 1:
        return None
    margin = run["trip_ms"] - run["gotit_ms"]
    waits = found["waits_ms"]
    over = [w for w in waits if w > margin]
    length = window_ms(run["run_dir"])
    if not waits or not over or length <= 0:
        return None
    rate = len(waits) / length
    share = len(over) / float(len(waits))
    excess = statistics.mean(w - margin for w in over)
    return {"a9_2": found["predicted"], "a9_2b": found["predicted_own"], "waits_per_ms": rate,
            "share_over": share, "mean_excess_ms": excess,
            "product": min(1.0, rate * share * excess)}


def events_by_thread(path):
    """{tid: [(ns, kind)]} for every thread in a waits.txt, in time order."""
    found = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.split()
            if (len(parts) == 3 and parts[0] in ("P", "S", "R", "W") and parts[1].isdigit()
                    and parts[2].isdigit()):
                found.setdefault(int(parts[1]), []).append((int(parts[2]), parts[0]))
    for tid in found:
        found[tid].sort()
    return found


def waits_by_cause(path):
    """({"wake": [ms], "preempt": [ms]}): every python3 thread's waits for a CPU over the whole
    recording, by what began them."""
    found = {"wake": [], "preempt": []}
    for evts in events_by_thread(path).values():
        #: As helper_waits.Timeline reads them: a wake-up moves only a sleeping thread (or one not
        #: yet seen) to waiting; a thread on its CPU is not woken into anything.
        state, began = None, None
        for ns, kind in evts:
            if kind == "R":
                if state in found:
                    found[state].append((ns - began) / 1e6)
                state = "running"
            elif kind == "P":
                state, began = "preempt", ns
            elif kind == "S":
                state = "asleep"
            elif state in (None, "asleep"):
                state, began = "wake", ns
    return found


def _share(values, over):
    return sum(1 for v in values if v > over) / float(len(values)) if values else None


def binned(waits, edges=BAND_EDGES):
    """How many of the waits fall in each (low, high] bin."""
    counts = [0] * (len(edges) - 1)
    for wait in waits:
        i = bisect.bisect_left(edges, wait) - 1
        if 0 <= i < len(counts):
            counts[i] += 1
    return counts


def band_ratio(counts, edges=BAND_EDGES, band=(A9_SLICE_MS, A9_SLICE_MS + A9_TICK_MS),
               against=(1.0, A9_SLICE_MS)):
    """The waits' density a ms in the band from the slice to a tick past it, over their density
    between 1 ms and the slice: about 1 for waits spread evenly below the slice."""
    def density(low, high):
        return sum(n for n, a, b in zip(counts, edges, edges[1:])
                   if a >= low and b <= high) / (high - low)
    base = density(*against)
    return density(*band) / base if base else None


def own_waits(run):
    """Every acknowledgement's own wait for a CPU in ms, read as helper_waits.a9_run reads them for
    A9-2b -- from the later of its stamper's last wake from sleep and that thread's previous stamp
    -- or None where a9_run does not read the run."""
    found, _ = helper_waits.a9_run(run)
    if found is None:
        return None
    records = helper_waits.thread_records(run["run_dir"])
    stampers = sorted(records["producer"]["roles"]["stamps_ack"])
    evts, _ = helper_waits.events(os.path.join(run["run_dir"], "waits.txt"), stampers)
    lines = dict((tid, helper_waits.Timeline(found)) for tid, found in evts.items())
    producer = helper_waits.to_monotonic(records["producer"])
    own, previous = [], {}
    for _, ack, _ in sorted(helper_waits.messages(run["run_dir"], helper_waits.WARMUP_S),
                            key=lambda message: message[1]):
        stamp = producer(ack)
        on = [tid for tid in stampers if lines[tid].at(stamp) == "running"]
        if len(on) == 1:
            wait = lines[on[0]].own_wait(stamp, previous.get(on[0]))
            previous[on[0]] = stamp
            if wait is not None:
                own.append(wait / 1e6)
    return own


def survival(waits, at=AT_MS):
    """S(x): the share of the waits longer than each x in `at`."""
    ordered = sorted(waits)
    return [1.0 - bisect.bisect_right(ordered, x) / float(len(ordered)) for x in at]


def fitted(shares, shape, at=AT_MS, s=A9_SLICE_MS, h=A9_TICK_MS):
    """{scale, rms_of_scale}: the one scale p that brings p F(x) nearest the shares by least
    squares, and the root mean square of what is left, as a share of p."""
    model = [shape(x, s, h) for x in at]
    scale = sum(m * y for m, y in zip(model, shares)) / sum(m * m for m in model)
    left = math.sqrt(sum((y - scale * m) ** 2 for m, y in zip(model, shares)) / len(shares))
    return {"scale": scale, "rms_of_scale": left / scale if scale else None}


def wait_shape(folders):
    """{"pair, backend, load": {runs, acks, shares, over_2_of_over_1, over_3_of_over_1,
    past_4_of_over_1, <shape>: {scale, rms_of_scale}}}, every recorded A9 run's acknowledgements
    pooled."""
    pooled, runs = {}, {}
    for run in helper_waits.counted_runs(folders, ("A9",)):
        waits = own_waits(run)
        if not waits:
            continue
        key = "%s, %s, %s" % (run["pair"], run["backend"], run["load_pct"])
        pooled.setdefault(key, []).extend(waits)
        runs[key] = runs.get(key, 0) + 1
    found = {}
    for key, waits in sorted(pooled.items()):
        shares = survival(waits)
        at = dict(zip(AT_MS, shares))
        entry = {"runs": runs[key], "acks": len(waits), "shares": shares,
                 "over_2_of_over_1": at[2.0] / at[1.0] if at[1.0] else None,
                 "over_3_of_over_1": at[3.0] / at[1.0] if at[1.0] else None,
                 "past_4_of_over_1": at[4.0] / at[1.0] if at[1.0] else None}
        for name, shape in sorted(WAIT_SHAPES.items()):
            entry[name] = fitted(shares, shape)
        found[key] = entry
    return found


# --- every run -------------------------------------------------------------------------------------

def a9_rows(folders):
    """One row per recorded A9 run: what decompose says, the run's measured rate, and its waits
    by cause."""
    rows = []
    for run in helper_waits.counted_runs(folders, ("A9",)):
        path = os.path.join(run["run_dir"], "waits.txt")
        if not os.path.exists(path) or run.get("gotit_ms") is None:
            continue
        parts = decompose(run) or {}
        causes = waits_by_cause(path)
        rows.append(dict(parts, pair=run["pair"], backend=run["backend"], setup=run["setup"],
                         run=run["run"], measured=run["negative_rate"],
                         wake_waits=len(causes["wake"]), preempt_waits=len(causes["preempt"]),
                         wake_over_1ms=_share(causes["wake"], LONG_MS),
                         preempt_over_1ms=_share(causes["preempt"], LONG_MS),
                         wake_bins=binned(causes["wake"]),
                         preempt_bins=binned(causes["preempt"])))
    return rows


def recording_effect(folders, blocks=("A9",), recording="waits.txt"):
    """{pair, backend: [recorded / unrecorded rate, by setup]}: each setup's recorded runs' mean
    negative rate over its unrecorded runs', where the unrecorded ones measured any. A9 records
    every event (waits.txt); A6, in A1's and A3's runs, one histogram (runqlat.txt)."""
    setups = {}
    for run in helper_waits.counted_runs(folders, blocks):
        side = os.path.exists(os.path.join(run["run_dir"], recording))
        key = (run["pair"], run["backend"], run["setup"])
        setups.setdefault(key, {True: [], False: []})[side].append(run["negative_rate"])
    found = {}
    for (pair, backend, _), sides in sorted(setups.items()):
        if sides[True] and sides[False] and statistics.mean(sides[False]) > 0:
            found.setdefault("%s, %s" % (pair, backend), []).append(
                statistics.mean(sides[True]) / statistics.mean(sides[False]))
    return found


def a6_rows(folders):
    """One row per A6 histogram: how many waits it holds, and the share over 1 ms."""
    rows = []
    for run in helper_waits.counted_runs(folders, ("A1", "A3")):
        path = os.path.join(run["run_dir"], "runqlat.txt")
        if not os.path.exists(path):
            continue
        bins = helper_waits.histogram(path)
        rows.append({"pair": run["pair"], "backend": run["backend"], "run": run["run"],
                     "waits": sum(n for _, _, n in bins),
                     "over_1ms": helper_waits.share_longer(bins, LONG_MS * 1000)})
    return rows


def _median(values):
    kept = [v for v in values if v is not None]
    return statistics.median(kept) if kept else None


def summary(a9, effect, a6, a6_effect=None):
    a6_effect = a6_effect or {}
    parts = {}
    for row in a9:
        parts.setdefault("%s, %s" % (row["pair"], row["backend"]), []).append(row)
    out = {"a9": {}, "a6": {}}
    for name, rows in sorted(parts.items()):
        read = [r for r in rows if r.get("a9_2") and r.get("a9_2b")]
        out["a9"][name] = {
            "runs": len(rows), "decomposed": len(read),
            "a9_2_over_a9_2b": _median([r["a9_2"] / r["a9_2b"] for r in read]),
            "waits_per_s": _median([1000.0 * r["waits_per_ms"] for r in read]),
            "mean_excess_ms": _median([r["mean_excess_ms"] for r in read]),
            "rate_times_excess": _median([r["waits_per_ms"] * r["mean_excess_ms"] for r in read]),
            "share_over_by_acks": _median([r["share_over"] / r["a9_2b"] for r in read]),
            "identity_holds": all(abs(r["product"] - r["a9_2"]) < 1e-9 for r in read),
            "recorded_over_unrecorded": _median(effect.get(name, [])),
            "wake_waits": _median([r["wake_waits"] for r in rows]),
            "preempt_waits": _median([r["preempt_waits"] for r in rows]),
            "wake_over_1ms": _median([r["wake_over_1ms"] for r in rows]),
            "preempt_over_1ms": _median([r["preempt_over_1ms"] for r in rows])}
        for cause in ("wake", "preempt"):
            counts = [sum(column) for column in zip(*[r[cause + "_bins"] for r in rows
                                                      if r.get(cause + "_bins")])]
            out["a9"][name][cause + "_bins"] = counts or None
            out["a9"][name][cause + "_band_ratio"] = band_ratio(counts) if counts else None
    by = {}
    for row in a6:
        by.setdefault("%s, %s" % (row["pair"], row["backend"]), []).append(row)
    for name, rows in sorted(by.items()):
        out["a6"][name] = {"runs": len(rows), "waits": _median([r["waits"] for r in rows]),
                           "over_1ms": _median([r["over_1ms"] for r in rows]),
                           "recorded_over_unrecorded": _median(a6_effect.get(name, []))}
    return out


# --- the command -------------------------------------------------------------------------------------

def _r(value, places=4):
    return round(value, places) if isinstance(value, float) else value


A9_FIELDS = ["pair", "backend", "setup", "run", "measured", "a9_2", "a9_2b", "waits_per_ms",
             "share_over", "mean_excess_ms", "product", "wake_waits", "preempt_waits",
             "wake_over_1ms", "preempt_over_1ms"]


def write_shape(shape, out_dir):
    """ack_waits.csv, S(x) and each fitted shape's p F(x) at every x, and ack_wait_shape.json."""
    os.makedirs(out_dir, exist_ok=True)
    names = sorted(WAIT_SHAPES)
    with open(os.path.join(out_dir, "ack_waits.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["pair", "backend", "load_pct", "x_ms", "share"] + names)
        for key, entry in sorted(shape.items()):
            for x, share in zip(AT_MS, entry["shares"]):
                w.writerow(key.split(", ") + [x, _r(share, 6)] + [
                    _r(entry[name]["scale"] * WAIT_SHAPES[name](x, A9_SLICE_MS, A9_TICK_MS), 6)
                    for name in names])
    kept = dict((key, dict((k, v) for k, v in entry.items() if k != "shares"))
                for key, entry in shape.items())
    with open(os.path.join(out_dir, "ack_wait_shape.json"), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write(json.dumps({"slice_ms": A9_SLICE_MS, "tick_ms": A9_TICK_MS, "parts": kept},
                            indent=2, sort_keys=True) + "\n")


def shape_lines(shape):
    out = ["Each acknowledgement's own wait against the two shapes (A9-3 in full; decides nothing)"]
    for key, entry in sorted(shape.items()):
        out.append("  %s: %d acks, S(3)/S(1) %s (whole slice 1, rest of a slice 0.2); left over, "
                   "as a share of p: whole slice %s, rest of a slice %s" % (
                       key, entry["acks"], _r(entry["over_3_of_over_1"], 3),
                       _r(entry["whole slice"]["rms_of_scale"], 3),
                       _r(entry["rest of a slice"]["rms_of_scale"], 3)))
    return out


def write(a9, a6, found, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "a9_runs.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=A9_FIELDS, lineterminator="\n")
        w.writeheader()
        for row in a9:
            w.writerow(dict((k, _r(row.get(k), 6)) for k in A9_FIELDS))
    with open(os.path.join(out_dir, "a6_histograms.csv"), "w", newline="",
              encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["pair", "backend", "run", "waits", "over_1ms"],
                           lineterminator="\n")
        w.writeheader()
        for row in a6:
            w.writerow(dict((k, _r(v, 6)) for k, v in row.items()))
    with open(os.path.join(out_dir, "a9_summary.json"), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write(json.dumps(found, indent=2, sort_keys=True) + "\n")


def lines(found):
    out = ["A9-2 against A9-2b, the recording's effect, and A6 against A9 (decides nothing)"]
    for name, part in found["a9"].items():
        out.append("  %s: A9-2/A9-2b %s = waits a ms x mean excess %s x share over / by acks %s; "
                   "recorded/unrecorded rate %s; at the slice, wake-ups %s, preemptions %s" % (
                       name, _r(part["a9_2_over_a9_2b"], 3), _r(part["rate_times_excess"], 3),
                       _r(part["share_over_by_acks"], 3), _r(part["recorded_over_unrecorded"], 2),
                       _r(part["wake_band_ratio"], 2), _r(part["preempt_band_ratio"], 2)))
    for name, part in found["a6"].items():
        out.append("  A6 %s: %s waits a run, %s over 1 ms; recorded/unrecorded rate %s"
                   % (name, _r(part["waits"], 0), _r(part["over_1ms"], 3),
                      _r(part["recorded_over_unrecorded"], 2)))
    return out


def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="A9-2 against A9-2b, and A6 against A9")
    ap.add_argument("--a9", nargs="+", required=True, help="A9's campaign folders of runs")
    ap.add_argument("--a6", nargs="*", default=[], help="A1's and A3's campaign folders")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)
    try:
        a9 = a9_rows(args.a9)
        if not a9:
            raise ValueError("no recorded A9 run under %s" % ", ".join(args.a9))
        a6 = a6_rows(args.a6)
        found = summary(a9, recording_effect(args.a9), a6,
                        recording_effect(args.a6, ("A1", "A3"), "runqlat.txt"))
        shape = wait_shape(args.a9)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("ERROR: %s" % exc, file=out)
        return 2
    if args.out:
        write(a9, a6, found, args.out)
        write_shape(shape, args.out)
    for line in lines(found) + shape_lines(shape):
        print(line, file=out)
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
