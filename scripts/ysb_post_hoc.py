#!/usr/bin/env python3
"""
ysb_post_hoc.py -- the Yahoo Streaming Benchmark's runs, read after them.

No plan registered either reading here; each answers a question freeze 33's runs raised, and the
verdicts the frozen judges gave stand beside them unchanged.

**Why its figure ran ahead of T1's delay** (the flush table). Freeze 33 predicted that YSB's
figures would not follow T1's staircase (D36-5), and they did not, but they moved by far more than
the delay, not by less, as the prediction's reason had it. The reason is in how the processor
writes. Once a second its flusher walks every campaign window that took an event since the last
flush (CampaignProcessorCommon.java:41-55, :96-103) and writes each with synchronous Jedis calls:
four for a window Redis already holds -- hmget, hincrBy, hset, lpush -- and more for a new one
(:74-94). Each call waits for its reply, and T1 delays every packet from the broker's machine,
where Redis runs, to the driver's, where the processor runs. Its figure is a window's last write
less the window's end. So the delay is paid four times for each campaign before the next
campaign's window is written, and the later a campaign's place in the flush, the later its
window's figure.

The test is how far apart one window's writes for successive campaigns are, which should grow by
about four times the delay added. The generator's collection writes, campaign after campaign, each
campaign's windows newest first, as the window's last write less its start, in whole milliseconds
(core.clj:130-149, updated.txt). Where every campaign holds the same number of windows, the j-th
value of each campaign is the same window. A run whose count of values is not a whole multiple of
the hundred campaigns cannot be split into windows from the file, and is left out. The newest
window may still have been open when it was collected, and is left out too. Sorted, one window's
hundred values step from one write to the next. A step of 40 ms or more is not one write to the
next at any delay T1 ran: at 2 ms added, consecutive writes were some 11 ms apart, and some 30
with a new window's write between them. Such steps are left out, and the median of the rest is the
run's gap. The median does not change if the cut is 60 ms instead; a mean would.

**What its clock-moved runs fit** (the fit table). Freeze 21's judge rules a behaviour out when the
change it predicts from the reference's no-offset figures to the moved run's differs from the
change the tool showed from its own no-offset control by more than the control's noise allows.
Every behaviour's change is taken from the same base, the reference with nothing dropped, so a
tool that drops a share of its values at no offset -- YSB's notebook drops every window whose last
write came before the window's end -- starts each behaviour's change from the wrong place. Read
directly instead: what "drops the negatives" predicts the run keeps, and its average, against what
the run kept and printed. The judge wrote both into each run's verdict.json; the control's
reading gives the share its notebook dropped with no clock moved.

    python3 scripts/ysb_post_hoc.py --root runs/azure/collected/matched-b/v36_<stamp>/x/runs/azure \\
        --flush docs/results/tools/ysb_flush.csv --fit docs/results/tools/ysb_t2_fit.csv
"""
import argparse
import csv
import json
import os
import re
import statistics
import sys

#: The campaigns the benchmark's setup makes (its default, kept by tools_run.sh).
CAMPAIGNS = 100

#: The largest step between two values of one window still read as one write to the next.
WRITE_STEP_MS = 40

#: Freeze 33's four rounds, by the folder each ran in under the block's root.
ROUNDS = (("1", "tools_v36"), ("2", "tools_v36_round2"), ("3", "tools_v36_round3"),
          ("4", "tools_v36_round4"))

FLUSH_FIELDS = ("round", "added_ms", "values", "windows", "steps", "gap_ms")
FIT_FIELDS = ("round", "offset_ms", "sent", "kept", "avg_ms", "reference", "predicted_kept",
              "predicted_avg_ms")

#: The behaviour YSB's source predicts under T2 (D36-5), whose absolute figures are read here.
BEHAVIOUR = "drops the negatives"

STEP_DIR = re.compile(r"^t1-ysb-(\d+)(?:_(\d+))?ms$")


def added_ms(folder):
    """The delay a T1 run added, from the name of its folder: t1-ysb-0_3ms is 0.3 ms; None for a
    folder that is not one of the staircase's runs."""
    m = STEP_DIR.match(folder)
    if not m:
        return None
    return float("%s.%s" % (m.group(1), m.group(2) or "0"))


def gap(values, campaigns=CAMPAIGNS, cut_ms=WRITE_STEP_MS):
    """One run's windows, the steps read as one write to the next, and their median, in ms; None
    where the run's values cannot be split into windows (see the module's docstring)."""
    if not values or len(values) % campaigns:
        return None
    width = len(values) // campaigns
    steps = []
    for j in range(1, width):
        column = sorted(values[i * width + j] for i in range(campaigns))
        steps += [b - a for a, b in zip(column, column[1:]) if b - a < cut_ms]
    if not steps:
        return None
    return width - 1, len(steps), statistics.median(steps)


def flush_rows(rnd, folder):
    """A round's flush rows: one for each staircase run under its folder, by the delay."""
    rows = []
    for name in sorted(os.listdir(folder)):
        added = added_ms(name)
        path = os.path.join(folder, name, "updated.txt")
        if added is None or not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            values = [int(v) for v in fh.read().split()]
        found = gap(values)
        windows, steps, median = found if found else ("", "", "")
        rows.append({"round": rnd, "added_ms": "%.1f" % added, "values": len(values),
                     "windows": windows, "steps": steps,
                     "gap_ms": "" if median == "" else "%.1f" % median})
    return sorted(rows, key=lambda r: float(r["added_ms"]))


def fit_rows(rnd, folder):
    """A round's fit rows: its no-offset control first, then each clock-moved run by its offset.
    The control's row carries only what it kept of what it wrote, and its average."""
    rows = []
    control = os.path.join(folder, "t2-ysb-control", "reading.json")
    if os.path.exists(control):
        with open(control, encoding="utf-8") as fh:
            got = json.load(fh)
        rows.append({"round": rnd, "offset_ms": "0", "sent": got["received"], "kept": got["kept"],
                     "avg_ms": "%.1f" % got["reported_ms"]["avg"], "reference": "",
                     "predicted_kept": "", "predicted_avg_ms": ""})
    moved = []
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name, "verdict.json")
        if not name.startswith("t2-ysb-") or not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            verdict = json.load(fh)
        expected = verdict["expected"][BEHAVIOUR]
        moved.append({"round": rnd, "offset_ms": "%.4f" % verdict["offset_ms"],
                      "sent": verdict["sent"], "kept": verdict["count_reported"],
                      "avg_ms": "%.1f" % verdict["reported_avg_ms"],
                      "reference": verdict["reference_trips"],
                      "predicted_kept": expected["count"],
                      "predicted_avg_ms": "%.1f" % expected["avg_ms"]})
    return rows + sorted(moved, key=lambda r: float(r["offset_ms"]))


def block_rows(root, read, rounds=ROUNDS):
    rows = []
    for rnd, folder in rounds:
        path = os.path.join(root, folder)
        if os.path.isdir(path):
            rows += read(rnd, path)
    return rows


def slopes(rows):
    """Each round's least-squares slope of its gap against the delay added, over the runs that
    could be split into windows, in ms per ms; a round with fewer than two delays has none."""
    by_round = {}
    for r in rows:
        if r["gap_ms"] != "":
            by_round.setdefault(r["round"], []).append((float(r["added_ms"]), float(r["gap_ms"])))
    found = {}
    for rnd, xy in sorted(by_round.items()):
        if len({x for x, _ in xy}) < 2:
            continue
        mx = sum(x for x, _ in xy) / len(xy)
        my = sum(y for _, y in xy) / len(xy)
        found[rnd] = (sum((x - mx) * (y - my) for x, y in xy)
                      / sum((x - mx) ** 2 for x, _ in xy))
    return found


def _write(rows, fields, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", required=True, help="the block's runs/azure folder")
    ap.add_argument("--flush", required=True, help="the flush table to write")
    ap.add_argument("--fit", required=True, help="the fit table to write")
    args = ap.parse_args(argv)
    flush = block_rows(args.root, flush_rows)
    fit = block_rows(args.root, fit_rows)
    if not flush or not fit:
        print("no YSB staircase or clock-moved runs under %s" % args.root)
        return 1
    _write(flush, FLUSH_FIELDS, args.flush)
    _write(fit, FIT_FIELDS, args.fit)
    split = sum(1 for r in flush if r["gap_ms"] != "")
    print("%d of %d staircase runs split into windows; gap slope per round, ms per ms: %s"
          % (split, len(flush), ", ".join("%s: %.2f" % kv for kv in slopes(flush).items())))
    print("%d clock-moved runs read against %r" % (sum(1 for r in fit if r["reference"] != ""),
                                                   BEHAVIOUR))
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
