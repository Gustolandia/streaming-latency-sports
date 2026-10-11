#!/usr/bin/env python3
"""
kafka_clamp.py -- K1: what Kafka's own end-to-end tool does with a message that arrives first.

Kafka's EndToEndLatency sends each record synchronously, waits for the broker's acknowledgment,
and only then polls its consumer for the record (3.7.1, EndToEndLatency.java:110-114). A record
that a consumer could already read before the acknowledgment came back is therefore timed no
earlier than the acknowledgment: the receipt-minus-acknowledgment difference this paper measures
is held at zero by the order of two calls, and nothing in the tool's output says so.

K1 shows how often that happens and what it does to the figures. A copy of the tool, changed only
to write down for each record its offset and the wall-clock instants at which it began, at which
`get()` returned the acknowledgment and at which the poll returned (external/kafka_e2e), runs
beside an independent consumer on the same host and the same wall clock that writes down when each
offset became readable to it. Paired by offset, each record gives

    S          = arrival - acknowledgment       below zero: the record was readable first
    tool       = the tool's own elapsed time    what it prints, and what its percentiles use
    observed   = arrival - begin                the end to end time the observer saw

and a record with S below zero is one the tool timed late, by -S plus whatever its own poll took.

    python3 scripts/kafka_clamp.py judge --trace e2e_trace.csv --arrivals arrivals.csv \\
        --out k1.json

and the block, every round's four cells and K1-a to K1-d as freeze 32 froze them (D35-7):

    python3 scripts/kafka_clamp.py block --root runs/azure/collected/matched/v35_<stamp>/x/runs/azure \\
        --out docs/results/tools/k1.csv --verdicts docs/results/tools/k1_verdicts.json
"""
import argparse
import csv
import json
import os
import statistics
import sys


def _rows(path):
    """A file's complete rows, and how many were torn.

    A row is complete when its line ends: a writer stopped in the middle of a line leaves its last
    field cut short, and a cut timestamp is still a number -- in the pilot of 11 October one put the
    observed average at minus 735 million ms. A row missing a field is torn the same way."""
    with open(path, encoding="utf-8", newline="") as fh:
        text = fh.read()
    torn = 0
    if text and not text.endswith("\n"):
        text, torn = text[:text.rfind("\n") + 1], 1
    rows = [r for r in csv.DictReader(text.splitlines())]
    whole = [r for r in rows if None not in r.values() and None not in r and all(r.values())]
    return whole, torn + len(rows) - len(whole)


def kafka_percentile(values_ms, q):
    """A percentile as EndToEndLatency prints it: whole milliseconds, sorted, indexed at n * q
    (EndToEndLatency.java:122 and 167-170 in 3.7.1)."""
    whole = sorted(int(v) for v in values_ms)
    return whole[int(len(whole) * q)]


def _quantile(values, q):
    """The q-th quantile by linear interpolation between order statistics."""
    v = sorted(values)
    pos = (len(v) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def pair(trace, arrivals):
    """Each traced record with the instant the observer read it, by (partition, offset).

    Returns the paired records and how many traced records the observer never read, which is
    reported rather than dropped: an observer that missed records would bias the share."""
    seen = {}
    for a in arrivals:
        key = (a["partition"], a["offset"])
        at = int(a["arrival_us"])
        seen[key] = min(at, seen.get(key, at))
    out, missed = [], 0
    for t in trace:
        key = (t["partition"], t["offset"])
        if key not in seen:
            missed += 1
            continue
        begin, ack, poll = int(t["begin_us"]), int(t["ack_us"]), int(t["poll_us"])
        out.append({"i": int(t["i"]), "s_ms": (seen[key] - ack) / 1000.0,
                    "tool_ms": int(t["elapsed_ns"]) / 1e6,
                    "observed_ms": (seen[key] - begin) / 1000.0,
                    "late_by_ms": (poll - seen[key]) / 1000.0,
                    "ack_ms": (ack - begin) / 1000.0})
    return out, missed


def judge(trace, arrivals):
    """K1's figures for one run."""
    paired, missed = pair(trace, arrivals)
    if not paired:
        return {"traced": len(trace), "paired": 0, "missed_by_observer": missed,
                "why": "no traced record was read by the observer, so nothing can be paired"}
    early = [p for p in paired if p["s_ms"] < 0]
    tool = [p["tool_ms"] for p in paired]
    observed = [p["observed_ms"] for p in paired]
    s = [p["s_ms"] for p in paired]
    out = {
        "traced": len(trace),
        "paired": len(paired),
        "missed_by_observer": missed,
        "early": len(early),
        "early_share": len(early) / len(paired),
        "s_ms": {"p01": _quantile(s, 0.01), "p50": _quantile(s, 0.5), "p99": _quantile(s, 0.99)},
        "tool_prints": {"avg": statistics.mean(tool), "p50": kafka_percentile(tool, 0.5),
                        "p99": kafka_percentile(tool, 0.99)},
        "observed_ms": {"avg": statistics.mean(observed), "p50": _quantile(observed, 0.5),
                        "p99": _quantile(observed, 0.99)},
        #: Every record's elapsed time covers its own acknowledgment: the instrument's check that
        #: the trace is the tool's own order of events, not a prediction.
        "elapsed_covers_ack": all(p["tool_ms"] + 0.001 >= p["ack_ms"] for p in paired),
    }
    if early:
        late = [p["late_by_ms"] for p in early]
        out["early_reported_late_by_ms"] = {"p50": _quantile(late, 0.5),
                                            "p99": _quantile(late, 0.99), "max": max(late)}
    return out


#: K1's cells, as T3's: load in percent, and whether the tool ran at real-time priority.
CELLS = (("0", "no"), ("0", "yes"), ("88", "no"), ("88", "yes"))
ROUNDS = 6
#: A run is judged only where the observer read at least this share of what the tool traced.
OBSERVED_AT_LEAST = 0.99
FIELDS = ("round", "load_pct", "go_first", "traced", "paired", "missed_by_observer", "torn_rows",
          "judged", "early", "early_share", "s_p01_ms", "s_p50_ms", "s_p99_ms", "late_p50_ms",
          "late_p99_ms", "late_max_ms", "tool_avg_ms", "tool_p50_ms", "tool_p99_ms",
          "observed_avg_ms", "observed_p50_ms", "observed_p99_ms", "elapsed_covers_ack")


def round_folder(root, rnd):
    """Round 1 is the block's own folder and each later round has its own, as tools.sh names them."""
    return os.path.join(root, "tools_v35" if rnd == 1 else "tools_v35_round%d" % rnd)


def block_rows(root, rounds=ROUNDS):
    """One row per round and cell, from each run's k1.json; a cell with none is a row that says so."""
    rows = []
    for rnd in range(1, rounds + 1):
        for load, first in CELLS:
            row = dict.fromkeys(FIELDS, "")
            row.update({"round": rnd, "load_pct": load, "go_first": first, "judged": False})
            path = os.path.join(round_folder(root, rnd), "k1-l%s-first%s" % (load, first), "k1.json")
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    got = json.load(fh)
                torn = got.get("torn_rows") or {}
                row.update({"traced": got.get("traced"), "paired": got.get("paired"),
                            "missed_by_observer": got.get("missed_by_observer"),
                            "torn_rows": sum(torn.values()) if torn else 0,
                            "early": got.get("early", ""), "early_share": got.get("early_share", ""),
                            "elapsed_covers_ack": got.get("elapsed_covers_ack", "")})
                for prefix, key in (("s", "s_ms"), ("tool", "tool_prints"), ("observed", "observed_ms")):
                    for name, value in (got.get(key) or {}).items():
                        row["%s_%s_ms" % (prefix, name)] = value
                for name, value in (got.get("early_reported_late_by_ms") or {}).items():
                    row["late_%s_ms" % name] = value
                row["judged"] = bool(got.get("traced")) and got.get("elapsed_covers_ack") is True \
                    and (got.get("paired") or 0) >= OBSERVED_AT_LEAST * got["traced"]
            rows.append(row)
    return rows


def verdicts(rows, rounds=ROUNDS):
    """K1-a over every run; K1-b to K1-d round by round, each holding only if it holds in every one.

    A prediction is said to hold or to fail where every round it needs was judged, and is
    otherwise undecided, with the rounds that were not."""
    share = {(r["round"], r["load_pct"], r["go_first"]): r for r in rows}
    ran = [r for r in rows if r["traced"] not in ("", None)]
    out = {"K1-a": {"verdict": "holds" if ran and all(r["elapsed_covers_ack"] is True for r in ran)
                    else "fails",
                    "runs": len(ran)}}
    tests = {
        "K1-b": ((("88", "no"),), lambda a: a[0] > 0),
        "K1-c": ((("88", "no"), ("0", "no")), lambda a: a[0] > a[1]),
        "K1-d": ((("88", "yes"), ("88", "no")), lambda a: a[0] < a[1]),
    }
    for name, (cells, holds) in tests.items():
        per_round, missing = {}, []
        for rnd in range(1, rounds + 1):
            got = [share.get((rnd,) + cell) for cell in cells]
            if not all(g and g["judged"] for g in got):
                missing.append(rnd)
                continue
            per_round[rnd] = holds([g["early_share"] for g in got])
        if missing:
            verdict = "undecided"
        else:
            verdict = "holds" if all(per_round.values()) else "fails"
        out[name] = {"verdict": verdict, "held_in_rounds": sorted(r for r, h in per_round.items() if h),
                     "failed_in_rounds": sorted(r for r, h in per_round.items() if not h),
                     "not_judged_in_rounds": missing}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="K1: Kafka's end-to-end tool against an observer")
    sub = ap.add_subparsers(dest="command", required=True)
    j = sub.add_parser("judge")
    j.add_argument("--trace", required=True, help="the traced tool's e2e_trace.csv")
    j.add_argument("--arrivals", required=True, help="the observer's arrivals.csv")
    j.add_argument("--out", default="")
    b = sub.add_parser("block")
    b.add_argument("--root", required=True, help="the folder holding tools_v35 and its rounds")
    b.add_argument("--out", required=True, help="the table, one row per round and cell")
    b.add_argument("--verdicts", required=True, help="K1-a to K1-d as JSON")
    args = ap.parse_args(argv)
    if args.command == "block":
        rows = block_rows(args.root)
        with open(args.out, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        found = verdicts(rows)
        with open(args.verdicts, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(found, indent=2, sort_keys=True) + "\n")
        print(json.dumps(found, sort_keys=True))
        return 0 if any(r["traced"] not in ("", None) for r in rows) else 1
    trace, torn_trace = _rows(args.trace)
    arrivals, torn_arrivals = _rows(args.arrivals)
    got = judge(trace, arrivals)
    #: Left out, and said to be: a torn row is never read as a short number.
    got["torn_rows"] = {"trace": torn_trace, "arrivals": torn_arrivals}
    text = json.dumps(got, indent=2, sort_keys=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)
    return 0 if got.get("paired") else 1


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
