"""The general method's numbers for the paper, read from its committed verdicts and designs.

Reads, under docs/results/general_method/:
- g_verdicts.json, the verdicts of plan version 47 (freeze 44, judged at 9e6c422c);
- g49_verdicts.json, the verdicts of plan version 49 (freeze 46, judged at 8f0799bd);
- g_runs.csv, plan version 47's run table, for the silences of the runs it could not judge;
- g49r_design.json, one of the judged designs, for the load each run switched on and off.

It returns ledger macros, (name, value) pairs. scripts/emit_paper_numbers.py writes them into
docs/generated/paper_numbers.tex, so its --check holds them like every other number. A range of
observed values is rounded outward, its low end down and its high end up, as the paper's ranges
are. It also renders Supplement S8.2's table of every prediction of the two plans and its verdict,
each bar taken from the judges' own thresholds.
"""
import csv
import json
import math
import os

import general_method as gm
import general_method49 as gm49

DIR = os.path.join("docs", "results", "general_method")

#: A count that is small enough is also given as a word, as IEEE style prints it in prose.
SPELLED = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
           "eleven", "twelve")


def spell(n):
    return SPELLED[n] if 0 <= n < len(SPELLED) else str(n)


def load(name, root="."):
    with open(os.path.join(root, DIR, name), encoding="utf-8") as fh:
        return json.load(fh)


def runs(name, root="."):
    """The rows of one committed run table."""
    with open(os.path.join(root, DIR, name), encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def checks(verdicts, key):
    """The checks of one prediction; a prediction judged in parts gives every part's checks."""
    entry = verdicts[key]
    if "checks" in entry:
        return list(entry["checks"])
    found = []
    for part in entry.get("parts", {}).values():
        found.extend(part.get("checks", []))
    return found


def one(values, what):
    """The single value every check agrees on, or an error naming what disagreed."""
    distinct = sorted(set(values))
    if len(distinct) != 1:
        raise ValueError("%s is not one value: %r" % (what, distinct))
    return distinct[0]


def thousands(n):
    """2000 -> 2{,}000, the ledger's way of writing a thousands separator."""
    return "{:,}".format(int(n)).replace(",", "{,}")


def down(x, places):
    f = 10 ** places
    return "%.*f" % (places, math.floor(x * f + 1e-9) / f)


def up(x, places):
    f = 10 ** places
    return "%.*f" % (places, math.ceil(x * f - 1e-9) / f)


def judged_rates(*verdict_sets):
    """The publish rate of every check of every prediction; "described" holds no prediction."""
    rates = []
    for verdicts in verdict_sets:
        for key, entry in verdicts.items():
            if key == "described" or not isinstance(entry, dict):
                continue
            rates.extend(c["rate"] for c in checks(verdicts, key) if "rate" in c)
    return rates


def macros(root="."):
    g47 = load("g_verdicts.json", root)
    g49 = load("g49_verdicts.json", root)
    design = load("g49r_design.json", root)
    out = [("gmRate", thousands(one(judged_rates(g47, g49), "the judged runs' rate")))]
    setups = design["setups"]
    out.append(("gmLoadPct", "%d" % one([s["load_pct"] for s in setups], "the load")))
    out.append(("gmLoadBlockS", "%d" % one([s["load_blocks_s"] for s in setups],
                                           "the load's blocks")))
    # Section IV-D: the late request, where a consumer keeps one request at a time.
    ra = one([c["W_ratio"] for c in checks(g49, "R-a")], "R-a's ratio")
    rise = one([c["W_rise"] for c in checks(g49, "R-a")], "R-a's rise")
    out.append(("gmRaWRatio", "%.2f" % ra))
    out.append(("gmRaWRiseMs", "%.2f" % (rise / 1000.0)))
    tc = [c["Tc_ratio"] for c in checks(g47, "KC-a")]
    out.append(("gmKCaTcRatioLo", down(min(tc), 1)))
    out.append(("gmKCaTcRatioHi", up(max(tc), 1)))
    kcb = [c for c in checks(g47, "KC-b") if c.get("judged", True)]
    out.append(("gmKCbWRatioLo", down(min(c["W_ratio"] for c in kcb), 2)))
    out.append(("gmKCbWRatioHi", up(max(c["W_ratio"] for c in kcb), 2)))
    # The share of W's rise that removing the consumer's time to ask again takes out, as a
    # percentage rounded down: "at least" this much in every client.
    out.append(("gmKCbSharePctLo",
                "%d" % math.floor(100.0 * min(c["share"] for c in kcb) + 1e-9)))
    return out + remedy_macros(g47, g49) + points_macros(g47, g49, runs("g_runs.csv", root))


def remedy_macros(g47, g49):
    """Section VI's numbers (3 Nov 2026): the check's estimate against the broker's record, the
    remedy by protocol and Kafka's fetch thread, and plan version 47's test of the hold."""
    # M2-b: the largest gap, in points, between the estimate's share of messages that found no
    # request waiting and the broker's share, over every run where the estimate has a value.
    gaps = [abs(p) for c in checks(g47, "M2-b") for p in (c.get("points") or []) if p is not None]
    out = [("gmMtwoBPointsHi", up(max(gaps), 1))]
    # R-c, J-b and G-b (plan 49): where requests or credit waited, W's tail held still while D's
    # own tail grew; the ranges are over the four setups, rounded outward.
    held = [c for key in ("R-c", "J-b", "G-b") for c in checks(g49, key)]
    out.append(("gmHoldRatioLo", down(min(c["W_ratio"] for c in held), 2)))
    out.append(("gmHoldRatioHi", up(max(c["W_ratio"] for c in held), 2)))
    out.append(("gmDGrowLo", down(min(c["D_own_ratio"] for c in held), 1)))
    out.append(("gmDGrowHi", up(max(c["D_own_ratio"] for c in held), 1)))
    # Q-a and Q-b: the client's part of Kafka's latency, W - F, its own tail at normal priority
    # with the load off and on, and its rise with only librdkafka's broker thread raised.
    qa = checks(g49, "Q-a")
    out.append(("gmQaFromUs", "%.0f" % one([c["WF_own_tail_off"] for c in qa], "Q-a's tail off")))
    out.append(("gmQaToMs", "%.2f" % (one([c["WF_own_tail_on"] for c in qa], "Q-a's tail on")
                                     / 1000.0)))
    qb = checks(g49, "Q-b")
    out.append(("gmQbRiseUs", "%.1f" % one([c["rise"] for c in qb], "Q-b's rise")))
    out.append(("gmQbSharePct", "%.2f" % (100.0 * one([c["left"] for c in qb], "Q-b's share"))))
    # Every prediction of plan 49, which the text says held: a verdict that is not "confirmed"
    # stops the build here instead of printing a claim the record does not make.
    keys = [k for k, e in g49.items() if k != "described" and isinstance(e, dict)]
    if any(g49[k]["verdict"] != "confirmed" for k in keys):
        raise ValueError("a prediction of plan 49 is not confirmed; the text says every one held")
    out.append(("gmLaterPredictions", "%d" % len(keys)))
    # M3-a (plan 47), not confirmed: over the judged cells W's tail held still but D's own on/off
    # ratio fell short of its bar.
    m3 = [c for c in checks(g47, "M3-a") if c.get("judged")]
    out.append(("gmMthreeADLo", down(min(c["D_ratio"] for c in m3), 2)))
    out.append(("gmMthreeADHi", up(max(c["D_ratio"] for c in m3), 2)))
    return out


#: The two setups whose card-to-kernel lag moved with the load while their tail of W held still,
#: as Supplement S8.2 names them (nats.go and RabbitMQ).
MOVED_LAG = ("G2000-rabbitmq-p1000", "J2000-nats-go")


def points_macros(g47, g49, runs47):
    """Supplement S8.2's numbers (3 Nov 2026): what decided the predictions that were not
    confirmed, the bound of the check for a waiting request, Kafka's round trip, the Arm pair's
    client's part, and the parts of W beside each tail of W that held still."""
    # M1-a over the x86 pair's setups; the Arm pair's card gives no timestamps of its own, so its
    # cells have no verdict.
    m1a = [c for c in checks(g47, "M1-a") if c["holds"] is not None]
    out = [("gmMoneAPnineUs", up(max(v for c in m1a for v in c["q_p99"]), 0)),
           ("gmMoneAFail", "%d" % sum(1 for c in m1a if not c["holds"])),
           ("gmMoneASetups", "%d" % len(m1a)),
           # The largest lead of the kernel's timestamp over the card's, and the card clock's
           # window, as whole microseconds and nanoseconds rounded up.
           ("gmMoneAEarlyUs", "%d" % math.ceil(-min(v for c in m1a for v in c["q_min"]) - 1e-9)),
           ("gmMoneAWindowNs", thousands(math.ceil(
               1000.0 * max(v for c in m1a for v in c["window_us"]) - 1e-9)))]
    # M1-c: the sockets' 99th percentile of W above the capture's, with one reply per read and
    # with the library's own reads, and the bar the first had to meet.
    m1c = checks(g47, "M1-c")
    single = [c["tail_diff"] / 1000.0 for c in m1c if c["one_reply"]]
    out += [("gmMoneCLoMs", down(min(single), 1)), ("gmMoneCHiMs", up(max(single), 1)),
            ("gmMoneCLibMs", "%.1f" % one([c["tail_diff"] / 1000.0 for c in m1c
                                           if not c["one_reply"]], "M1-c's library reads")),
            ("gmMoneCBarUs", "%.0f" % gm.M1C_ONE_US)]
    # The bound of the check for a waiting request in each plan, and the runs of the cell that
    # plan 47 could not judge, whose captures fell silent for longer than the bound.
    cells = g47["M2-c"]["out_of_reach"]
    mine = [r for r in runs47 if r["setup"] in cells]
    if not mine or any(r["b_checks"] != "False" for r in mine):
        raise ValueError("the text says the bound's check failed in every run of %s" % cells)
    silent = [float(r["silence_max_us"]) / 1000.0 for r in mine]
    out += [("gmBetaMs", "%.0f" % gm.CERTIFY_B_MS), ("gmBetaWideMs", "%.0f" % gm.CERTIFY_B_WIDE_MS),
            ("gmPaSilenceLoMs", down(min(silent), 1)), ("gmPaSilenceHiMs", up(max(silent), 1)),
            ("gmPrefetchWide", thousands(one([c["prefetch"] for c in checks(g47, "P-a")],
                                             "P-a's prefetch")))]
    # Q-c: with librdkafka's broker thread raised, the shares of messages that found no fetch
    # waiting, and the gap at the broker from one fetch's answer to the next fetch, with the
    # client's own time to ask again inside it.
    [qc] = checks(g49, "Q-c")
    out += [("gmQcNoneOnPct", "%.0f" % (100.0 * qc["unwaited_on"])),
            ("gmQcNoneOffPct", "%.0f" % (100.0 * qc["unwaited_off"])),
            ("gmQcGapUs", "%.0f" % qc["described"]["g_us"]),
            ("gmQcTurnUs", "%.0f" % qc["described"]["g_turnaround_us"])]
    # Z-a and Z-b: the client's part on the Arm pair, at normal priority and with the thread
    # raised.
    [za] = checks(g49, "Z-a")
    [zb] = checks(g49, "Z-b")
    out += [("gmZaFromUs", "%.0f" % za["WF_own_tail_off"]),
            ("gmZaToMs", "%.2f" % (za["WF_own_tail_on"] / 1000.0)),
            ("gmZbSharePct", "%.2f" % (100.0 * zb["left"]))]
    # The parts of W beside each tail that held still (R-c, J-b, G-b): the setups whose
    # card-to-kernel lag left the band the tests use, how far it fell, against their tails of W,
    # and W's ratio with that fall added back to its tail with the load on.
    held = {c["setup"] for key in ("R-c", "J-b", "G-b") for c in checks(g49, key)}
    parts = {s["setup"]: s for s in g49["described"]["setups"]}
    moved = sorted(s for s in held
                   if not 1.0 / gm.HOLDS_STILL <= parts[s]["Q_own_ratio"] <= gm.HOLDS_STILL)
    if tuple(moved) != MOVED_LAG:
        raise ValueError("the text names %s; the record's moved lags are %s" % (MOVED_LAG, moved))
    lag = [parts[s]["Q_own_ratio"] for s in moved]
    fall = [parts[s]["Q_own_tail_off"] - parts[s]["Q_own_tail_on"] for s in moved]
    tails = [parts[s][k] for s in moved for k in ("W_tail_off", "W_tail_on")]
    back = [(parts[s]["W_tail_on"] + parts[s]["Q_own_tail_off"] - parts[s]["Q_own_tail_on"])
            / parts[s]["W_tail_off"] for s in moved]
    out += [("gmQownLo", down(min(lag), 2)), ("gmQownHi", up(max(lag), 2)),
            ("gmQownFallUs", up(max(fall), 1)),
            ("gmWTailLoUs", down(min(tails), 0)), ("gmWTailHiUs", up(max(tails), 0)),
            ("gmQbackLo", down(min(back), 2)), ("gmQbackHi", up(max(back), 2))]
    # Section VIII (3 Nov 2026): plan 47's predictions, and how many it confirmed, did not confirm
    # and could not judge.
    verdicts = [g47[k]["verdict"] for k in predictions(g47)]
    out += [("gmFirstPredictions", "%d" % len(verdicts)),
            ("gmFirstConfirmedWord", spell(verdicts.count("confirmed"))),
            ("gmFirstNotConfirmedWord", spell(verdicts.count("not confirmed"))),
            ("gmFirstNotJudgedWord", spell(verdicts.count("not judged")))]
    return out


def number(x):
    """A threshold as the text writes it: 150.0 -> 150, 1.2 -> 1.2."""
    return "%g" % x


def tested(g47, g49):
    """Supplement S8.2's rows, plan by plan: each prediction, the point of the general method it
    tests (1 the kernel's timestamps and the broker's ids, 2 the check for a waiting request, 3
    the three latencies, 4 the remedy by protocol) and what it required, with every bar taken
    from the judge that applied it. The exact wording is in DESIGN47.md and DESIGN49.md."""
    grow = number(gm.GROWTH)
    held = "within $1/%s$ and $%s$" % (number(gm.HOLDS_STILL), number(gm.HOLDS_STILL))
    wide = thousands(one([c["prefetch"] for c in checks(g47, "P-a")], "P-a's prefetch"))
    wide49 = thousands(one([c["prefetch"] for c in checks(g49, "G-a")], "G-a's prefetch"))
    plan47 = (
        ("M1-a", "1", "the kernel's receive timestamp trails the card's by at most $%s\\,\\mu$s "
                      "at the 99th percentile, and never leads it by more than the card clock's "
                      "window" % number(gm.Q_P99_US)),
        ("M1-b", "1", "matching by the broker's ids pairs every message that the payload's ids "
                      "pair, and none differently"),
        ("M1-c", "1", "the sockets' 99th percentile of $W$ lies within $%s\\,\\mu$s of the "
                      "capture's with one reply per read, and at least $%s\\,\\mu$s above it with "
                      "the library's own reads, under load" % (number(gm.M1C_ONE_US),
                                                                number(gm.M1C_LIBRARY_US))),
        ("M2-a", "2", "the clients' timestamps never show a message as finding none when the "
                      "broker's record shows one waiting"),
        ("M2-b", "2", "the estimate of the share of messages that found none waiting lies within "
                      "$%s$ points of the broker's share" % number(gm.M2B_POINTS)),
        ("M2-c", "2", "with requests or credit kept waiting, the broker's record shows one waiting "
                      "for at least $%s\\%%$ of messages, and the clients' timestamps show it for "
                      "at least $%s\\%%$ of those, at $\\beta = %s$~ms" % (
                          number(100.0 * gm.M2C_WAITING), number(100.0 * gm.M2C_CERTIFIED),
                          number(gm.CERTIFY_B_MS))),
        ("M3-a", "3", "there, over the messages that found one waiting, the tail of $W$ holds %s "
                      "of its value with the load off, while the tail of $D$ rises at least "
                      "$%s$-fold" % (held, grow)),
        ("M3-b", "3", "with one request or credit at a time, the tail of $W$ rises at least "
                      "$%s$-fold, and removing the client's time to ask again takes out at least "
                      "half of the rise" % grow),
        ("V-a", "4", "as M3-a, on \\redis{} with requests kept waiting"),
        ("N-a", "4", "as M3-a, on NATS JetStream with requests kept waiting, by our consumer and "
                     "by nats.go"),
        ("P-a", "4", "as M3-a, on RabbitMQ with credit for $%s$ messages kept waiting"
                     % wide),
        ("KC-a", "4", "for each \\kafka{} client that fetches inside its poll call, the tail of its "
                      "time to ask again rises at least $%s$-fold" % grow),
        ("KC-b", "4", "where the tail of $W$ rises at least $%s$-fold, removing that time takes "
                      "out at least half of the rise" % grow),
        ("KC-c", "4", "librdkafka's rise of that tail is at most half of each of those clients'"),
        ("KC-d", "4", "with only librdkafka's broker thread at real-time priority: as M3-a, over "
                      "all messages"),
        ("KC-h", "4", "there, the ratio of the tail of the time to ask again is at most $%s$, and "
                      "in each load state at least half of the messages find no fetch waiting"
                      % number(gm.KC_H_RATIO)),
        ("C-a", "4", "with the consumer's polling thread alone on its core, the rise of the tail "
                     "of $W$ is at most a third of the baseline's"),
        ("A", "2, 4", "V-a, M2-c and KC-d on the Neoverse~N2 pair"),
    )
    plan49 = (
        ("R-a", "3", "\\redis{} with one request at a time: the tail of $W$ rises at least "
                     "$%s$-fold" % grow),
        ("R-b", "2", "\\redis{} with requests kept waiting: as M2-c"),
        ("R-c", "4", "there, the tail of $W$ over all messages holds %s, while $D$ over its own "
                     "largest $1\\%%$ rises at least $%s$-fold" % (held, grow)),
        ("R-d", "4", "the rise of the tail of $W$ there is at most a tenth of its rise with one "
                     "request at a time"),
        ("J-a", "2", "NATS JetStream with requests kept waiting, by our consumer and by nats.go: "
                     "as R-b"),
        ("J-b", "4", "as R-c, for each"),
        ("G-a", "2", "RabbitMQ with credit for $%s$ messages kept waiting: as R-b, at "
                     "$\\beta = %s$~ms" % (wide49, number(gm.CERTIFY_B_WIDE_MS))),
        ("G-b", "4", "as R-c"),
        ("Q-a", "3", "librdkafka at normal priority: the client's part, $W - F$, over its own "
                     "largest $1\\%%$, rises at least $%s$-fold" % grow),
        ("Q-b", "4", "with only its broker thread raised, that rise is at most a tenth of Q-a's, "
                     "and at most $%s\\,\\mu$s" % number(gm49.LEFT_US)),
        ("Q-c", "3", "with the thread raised, in each load state at least half of the messages "
                     "find no fetch waiting"),
        ("Z-a", "3", "as Q-a, on the Neoverse~N2 pair"),
        ("Z-b", "4", "as Q-b, on the Neoverse~N2 pair"),
    )
    return (("47", g47, plan47), ("49", g49, plan49))


def predictions(verdicts):
    """The keys of one plan's predictions: every entry that carries a verdict."""
    return sorted(k for k, e in verdicts.items() if isinstance(e, dict) and "verdict" in e)


def render_table(root="."):
    """Supplement S8.2's table (3 Nov 2026): one row per prediction of plan versions 47 and 49,
    what it required and its verdict, read from the judge's output. A plan whose verdicts list a
    prediction the table does not, or the other way round, stops the build."""
    g47 = load("g_verdicts.json", root)
    g49 = load("g49_verdicts.json", root)
    lines = ["% Generated by scripts/emit_paper_numbers.py, through "
             "scripts/general_method_numbers.py, from\n% docs/results/general_method/"
             "g_verdicts.json and g49_verdicts.json, with the judges' own\n% thresholds. Do not "
             "edit.\n",
             "\\begin{tabular}{@{}ll>{\\raggedright\\arraybackslash}p{0.70\\columnwidth}l@{}}\n",
             "\\toprule\n& Point & Required & Verdict \\\\\n"]
    for plan, verdicts, rows in tested(g47, g49):
        listed = sorted(key for key, _, _ in rows)
        if listed != predictions(verdicts):
            raise ValueError("plan %s: the table lists %s, the verdicts %s"
                             % (plan, listed, predictions(verdicts)))
        lines.append("\\midrule\n\\multicolumn{4}{@{}l}{Plan version %s} \\\\\n" % plan)
        lines.extend("%s & %s & %s & %s \\\\\n" % (key, point, what, verdicts[key]["verdict"])
                     for key, point, what in rows)
    lines.append("\\bottomrule\n\\end{tabular}\n")
    return "".join(lines)
