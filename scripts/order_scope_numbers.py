#!/usr/bin/env python3
"""Freeze 41's numbers for the paper and the supplement.

Every figure here is read through scripts/order_scope.py's own judges from the run tables its
reader committed under docs/results/order_scope, so no number the text prints can part from the
verdicts the record gives. scripts/emit_paper_numbers.py calls the two public functions:

    order_scope_macros(root)        -> [(macro name, value)]
    render_order_scope_table(root)  -> Supplement S3.11's table of verdicts, "" until every block
                                       is committed
"""
import math
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import order_scope  # noqa: E402

ROOT = os.path.join("docs", "results", "order_scope")
#: Each block, the run table its reader wrote, and its bin table (block K's alone has one).
BLOCKS = (("K", "k_runs.csv", "k_bins.csv"), ("R", "r_runs.csv", None),
          ("P", "p_runs.csv", None), ("L", "l_runs.csv", None), ("I", "i_runs.csv", None))
#: The ladder's rung at which load is judged (DESIGN.md, L-b; the pilot's D44-10).
JUDGED_RATE = 50
_SPELLED = ("zero", "one", "two", "three", "four", "five", "six",
            "seven", "eight", "nine", "ten", "eleven", "twelve")


def spell(n):
    """A small count as a word, as scripts/emit_paper_numbers.py spells them."""
    return _SPELLED[n] if 0 <= n < len(_SPELLED) else str(n)


def thousands(n):
    """2000 -> 2{,}000, the separator that survives LaTeX's math mode."""
    s = str(int(n))
    groups = []
    while s:
        groups.insert(0, s[-3:])
        s = s[:-3]
    return "{,}".join(groups)


def reading(root=ROOT):
    """{block: (run rows, verdicts, bin rows)} for each block whose run table is committed."""
    found = {}
    for block, runs, bins in BLOCKS:
        path = os.path.join(root, runs)
        if not os.path.exists(path):
            continue
        rows = order_scope.read_table(path)
        bin_rows = order_scope.read_table(os.path.join(root, bins)) if bins else []
        found[block] = (rows, order_scope.JUDGES[block](rows, bin_rows), bin_rows)
    return found


def _setup_value(rows, field, **match):
    """A setup's value as DESIGN.md defines it: the median over its runs of each run's value."""
    picked = [float(r[field]) for r in rows
              if all(r.get(k) == v for k, v in match.items()) and r.get(field) not in (None, "")]
    return statistics.median(picked) if picked else None


def control_macros(verdicts):
    """Block P: the slopes of W_so and D on the added delay, and how far A moved."""
    wso = [c["slope_ms_per_ms"] for c in verdicts["P-a"]["checks"]]
    d = [c["slope_ms_per_ms"] for c in verdicts["P-c"]["checks"]]
    moves = [100.0 * c["move"] for c in verdicts["P-b"]["checks"]]
    return [("osSlopeWLo", "%.2f" % min(wso)), ("osSlopeWHi", "%.2f" % max(wso)),
            ("osSlopeDLo", "%.2f" % min(d)), ("osSlopeDHi", "%.2f" % max(d)),
            ("osAMoveLoPct", "%.0f" % min(moves)), ("osAMoveHiPct", "%.0f" % max(moves))]


def ladder_macros(rows, verdicts):
    """Block L: agreement at every rung, W_so under load at the judged rung set against D, the
    pull flag at the top rung, and the runs at the middle rung whose S fell mostly below zero."""
    rates = sorted(set(r["rate"] for r in rows))
    top, mid = rates[-1], rates[len(rates) // 2]
    held = {c["backend"]: c for c in verdicts["L-b"]["checks"] if c["rate"] == JUDGED_RATE}
    kafka, redis = held["kafka"], held["redis"]

    def mean(backend, load, field):
        return _setup_value(rows, field, rate=JUDGED_RATE, backend=backend, load_pct=load)
    share = ((mean("redis", 88, "Wso_mean") - mean("redis", 0, "Wso_mean"))
             / (mean("redis", 88, "D_mean") - mean("redis", 0, "D_mean")))
    at_top = [c for c in verdicts["L-c"]["described"] if c["rate"] == top]
    flagged = [100.0 * c["flagged_share"] for c in at_top]
    extra = [c["Wso_flagged"] - c["Wso_unflagged"] for c in at_top]
    middle = [r for r in rows if r["rate"] == mid]
    split = sum(1 for r in middle if 2 * int(r["S_neg"]) > int(r["S_count"]))
    return [
        ("osTopRate", thousands(top)), ("osMidRate", thousands(mid)),
        ("osLadderAgreeHiUs", "%.1f" % max(c["median_us"] for c in verdicts["L-a"]["checks"])),
        ("osLadderKafkaMovePct", "%.1f" % (100.0 * abs(kafka["busy"] - kafka["idle"])
                                           / kafka["idle"])),
        ("osLadderRedisRisePct", "%.0f" % (100.0 * (redis["busy"] - redis["idle"])
                                           / redis["idle"])),
        ("osLadderRedisSharePct", "%.0f" % (100.0 * share)),
        ("osPullTopLoPct", "%.1f" % min(flagged)), ("osPullTopHiPct", "%.1f" % max(flagged)),
        ("osPullExtraLoUs", "%.0f" % min(extra)), ("osPullExtraHiUs", "%.0f" % max(extra)),
        ("osMidSplitRunsWord", spell(split)), ("osMidRunsWord", spell(len(middle))),
    ]


def idle_macros(verdicts):
    """Block I: Redis's share of S in the mode, on each boot."""
    decision = verdicts["I"]["decision"]
    return [("osBumpDefaultPct", "%.1f" % (100.0 * decision["bump_share_default"])),
            ("osBumpPollPct", "%.1f" % (100.0 * decision["bump_share_poll"]))]


def fifths_factor(bins, setup):
    """The largest factor, either way, between the observed and the predicted share of values below
    zero, over the bins of one setup that K-d judges (those with enough values below zero)."""
    worst = 1.0
    for b in bins:
        if b["setup"] == setup and int(b["negatives"]) >= order_scope.MIN_NEGATIVES:
            obs, pred = float(b["observed"]), float(b["predicted"])
            worst = max(worst, obs / pred, pred / obs)
    return worst


def order_macros(rows, verdicts, bins):
    """Block K: the kernel-timed margin on Kafka and the share of its values below zero that are late
    readings; on Redis, the runs in which the delivery came first, its lead, and the share of
    Redis's values below zero with S_k < 0; the acknowledging thread's delay under load; K-d's
    agreement in each fifth of the margin; and K-e's decision with no load. Redis's setups are those
    with the usual sixteen send workers (an empty `workers`)."""
    kafka = sorted(set(r["setup"] for r in rows if r["backend"] == "kafka"))
    margins = [_setup_value(rows, "Sk_median", setup=s) for s in kafka]
    late = max(verdicts["K-a"]["checks"], key=lambda c: c["negatives"])
    redis_runs = [r for r in rows if r["backend"] == "redis" and not r["workers"]]
    first = sum(1 for r in redis_runs if 2 * int(r["Sk_neg"]) > int(r["timed"]))
    redis = sorted(set(r["setup"] for r in redis_runs))
    leads = [-v for v in (_setup_value(rows, "Sk_median", setup=s) for s in redis) if v < 0]
    order = [100.0 * c["order_share"] for c in verdicts["K-b"]["described"] if c["setup"] in redis]
    delay = {c["backend"]: c for c in verdicts["K-c"]["checks"]}
    judged = {c["setup"]: c for c in verdicts["K-d"]["checks"]}
    factor = {r["backend"]: fifths_factor(bins, s) for s in judged
              for r in rows if r["setup"] == s}
    idle = next(d for d in verdicts["K-e"]["decision"] if d["load_pct"] == 0)
    return [
        ("osKafkaMarginLoUs", "%.0f" % min(margins)), ("osKafkaMarginHiUs", "%.0f" % max(margins)),
        ("osKafkaLatePct", "%.1f" % (100.0 * (1.0 - late["order_share"]))),
        ("osRedisFirstRuns", str(first)), ("osRedisRuns", str(len(redis_runs))),
        ("osRedisLeadLoUs", "%.0f" % min(leads)), ("osRedisLeadHiUs", "%.0f" % max(leads)),
        ("osRedisOrderLoPct", "%.0f" % min(order)), ("osRedisOrderHiPct", "%.0f" % max(order)),
        ("osDackLoadKafka", "%.0f" % (delay["kafka"]["busy"] / delay["kafka"]["idle"])),
        ("osDackLoadRedis", "%.0f" % (delay["redis"]["busy"] / delay["redis"]["idle"])),
        ("osDackBusyKafkaMs", "%.1f" % (delay["kafka"]["busy"] / 1e3)),
        ("osDackBusyRedisMs", "%.1f" % (delay["redis"]["busy"] / 1e3)),
        ("osKdFactorKafka", "%.2f" % factor["kafka"]), ("osKdFactorRedis", "%.2f" % factor["redis"]),
        ("osGilIdleSixteenPct", "%.1f" % (100.0 * idle["rate_sixteen"])),
        ("osGilIdleOnePct", "%.2f" % (100.0 * idle["rate_one_worker"])),
    ]


def two_figures(pct):
    """A percentage to two significant figures, as the paper prints a rate: 0.56, 3.7, 18."""
    if pct <= 0:
        return "0"
    return "%.*f" % (max(0, 1 - int(math.floor(math.log10(pct)))), pct)


def order_detail_macros(rows, verdicts, bins):
    """Block K described beside its verdicts, for referee B (M1 (i) to (iii), 16 Oct 2026): how
    often S_k fell below zero on Kafka, run by run; the acknowledging thread's median delay in
    every Kafka setup, and its 99th percentile idle and at real-time priority; in the two setups
    K-d judges, that delay for the readings below zero and for the rest, read after the verdicts
    from the run table's own columns; and the paper's p G(S_k) over those setups' fifths of the
    margin, which K-d described beside its own prediction, with the share measured in each."""
    kafka_runs = [r for r in rows if r["backend"] == "kafka"]
    shares = [int(r["Sk_neg"]) / float(r["timed"]) for r in kafka_runs]
    medians = [_setup_value(rows, "dack_median", setup=s)
               for s in sorted(set(r["setup"] for r in kafka_runs))]
    delay = {c["backend"]: c for c in verdicts["K-c"]["checks"]}
    out = [("osKafkaRuns", str(len(kafka_runs))),
           ("osKafkaSkUnderOneRuns", str(sum(1 for x in shares if x < 0.01))),
           ("osKafkaSkNegMostPct", "%.0f" % (100.0 * max(shares))),
           ("osDackMedianLoUs", "%.0f" % min(medians)), ("osDackMedianHiUs", "%.0f" % max(medians)),
           ("osDackIdleKafkaUs", "%.0f" % delay["kafka"]["idle"]),
           ("osDackRtKafkaUs", "%.0f" % delay["kafka"]["rt"]),
           ("osWaitedMs", "%.1f" % (order_scope.WAITED_US / 1e3))]
    for check in verdicts["K-d"]["checks"]:
        name = "Kafka" if "kafka" in check["setup"] else "Redis"
        fifths = [b for b in bins if b["setup"] == check["setup"]]
        pg = [100.0 * float(b["pG"]) for b in fifths]
        # The measured share in each fifth, beside which p G(S_k) is read (16 Oct 2026).
        seen = [100.0 * float(b["observed"]) for b in fifths]
        out += [("osDackNeg%sUs" % name,
                 thousands(round(_setup_value(rows, "dack_neg_median", setup=check["setup"])))),
                ("osDackPos%sUs" % name,
                 thousands(round(_setup_value(rows, "dack_pos_median", setup=check["setup"])))),
                ("osPg%sLoPct" % name, "%.1f" % min(pg)), ("osPg%sHiPct" % name, "%.1f" % max(pg)),
                ("osSeen%sLoPct" % name, "%.1f" % min(seen)),
                ("osSeen%sHiPct" % name, "%.1f" % max(seen))]
    return out


#: The ladder's rungs by name, lowest first, in the macros that describe each.
RUNGS = ("Fifty", "Mid", "Top")


def ladder_detail_macros(rows):
    """Block L at each rung on an idle host, the one setting every rung ran, described for the
    referees (A, M2 fix 3, and B, M3 fix 3; 16 Oct 2026): the negative-span rate beside the
    kernel-timed latency, and the share of reads that drained more than one packet; and the
    largest share of messages carrying the pull flag at the middle rung. Each is a setup's value
    as DESIGN.md defines it, the median over its runs of each run's own share."""
    rates = sorted(set(r["rate"] for r in rows))

    def share(backend, rate, part, whole):
        return order_scope._run_share([r for r in rows if r["backend"] == backend
                                       and r["rate"] == rate and r["load_pct"] == 0],
                                      part, whole)
    out = []
    for rate, rung in zip(rates, RUNGS):
        for backend in ("kafka", "redis"):
            out.append(("osRate%sAt%sPct" % (backend.capitalize(), rung),
                        two_figures(100.0 * share(backend, rate, "S_neg", "S_count"))))
        out.append(("osMultiKafkaAt%sPct" % rung,
                    "%.0f" % (100.0 * share("kafka", rate, "reads_multi", "reads"))))
    out += [("osMultiRedisMostPct", "%.2f" % max(100.0 * share("redis", rate, "reads_multi",
                                                                "reads") for rate in rates)),
            ("osPullMidMostPct", "%.1f" % max(100.0 * share(b, rates[1], "flagged", "flag_known")
                                              for b in ("kafka", "redis")))]
    return out


def order_scope_macros(root=ROOT):
    """Every freeze 41 macro whose block is committed."""
    read = reading(root)
    out = []
    if "K" in read:
        out += order_macros(*read["K"]) + order_detail_macros(*read["K"])
    if "P" in read:
        out += control_macros(read["P"][1])
    if "L" in read:
        out += ladder_macros(*read["L"][:2]) + ladder_detail_macros(read["L"][0])
    if "I" in read:
        out += idle_macros(read["I"][1])
    return out


def _times(x):
    return "%.2f" % x


def _ratio_cell(pairs):
    return "; ".join("\\%s{} $%s\\times$" % (b, _times(v)) for b, v in pairs)


def render_order_scope_table(root=ROOT):
    """Supplement S3.11: one row per prediction of freeze 41, what it required, what the runs gave
    and its verdict, all read from the judges' own output. Empty until every block is committed."""
    read = reading(root)
    if set(read) != set(b for b, _, _ in BLOCKS):
        return ""
    k, r, p, l, i = (read[b][1] for b in "KRPLI")
    kc = {c["backend"]: c for c in k["K-c"]["checks"]}
    ra = {c["backend"]: c for c in r["R-a"]["checks"]}
    rb = {c["backend"]: c for c in r["R-b"]["checks"]}
    pa, pb, pc = ({c["backend"]: c for c in p[n]["checks"]} for n in ("P-a", "P-b", "P-c"))
    both = ("kafka", "redis")
    idle = next(d for d in k["K-e"]["decision"] if d["load_pct"] == 0)
    busy = next(d for d in k["K-e"]["decision"] if d["load_pct"] == 88)
    held = [c for c in l["L-b"]["checks"]]
    rows = [
        ("K-v", "median gap between the journal's and the capture's acknowledgment arrival at "
                "most $20\\,\\mu$s in every setup",
         "largest median $%.1f\\,\\mu$s" % max(c["median_us"] for c in k["K-v"]["checks"]),
         k["K-v"]["verdict"]),
        ("K-a", "\\kafka{}: at least $90\\%$ of $S<0$ with $S_k \\geq 0$",
         "; ".join("$%.1f\\%%$ of $%s$" % (100.0 * (1 - c["order_share"]),
                                            thousands(c["negatives"]))
                   for c in k["K-a"]["checks"]), k["K-a"]["verdict"]),
        ("K-b", "\\redis{}, real-time: at least half of $S<0$ with $S_k<0$",
         "; ".join("$%.1f\\%%$ of $%s$" % (100.0 * c["order_share"], thousands(c["negatives"]))
                   for c in k["K-b"]["checks"]), k["K-b"]["verdict"]),
        ("K-c", "99th percentile of $\\delta_{\\mathrm{ack}}$: at least $1.5\\times$ under load, "
                "at most half at real-time priority",
         "; ".join("\\%s{} $%s\\times$, $%s\\times$" % (
             b, _times(kc[b]["busy"] / kc[b]["idle"]), _times(kc[b]["rt"] / kc[b]["busy"]))
             for b in both), k["K-c"]["verdict"]),
        ("K-d", "at $88\\%$, normal priority: the rate falls across the margin's fifths and lies "
                "within $2\\times$ of the delays' prediction",
         "; ".join("\\%s{} within $%s\\times$, %s" % (
             c["setup"].split("-")[1], _times(fifths_factor(read["K"][2], c["setup"])),
             "falls" if c["falls"] else "does not fall") for c in k["K-d"]["checks"]),
         k["K-d"]["verdict"]),
        ("K-e", "one publish worker against sixteen, \\redis{} real-time",
         "idle $%.2f\\%%$ against $%.2f\\%%$; $88\\%%$ load $%.2f\\%%$ against $%.2f\\%%$" % (
             100.0 * idle["rate_one_worker"], 100.0 * idle["rate_sixteen"],
             100.0 * busy["rate_one_worker"], 100.0 * busy["rate_sixteen"]), "decision"),
        ("R-a", "rate of $S<0$ without run-to-parity at most $2/3$ of the rate with it",
         _ratio_cell((b, ra[b]["off"] / ra[b]["on"]) for b in both), r["R-a"]["verdict"]),
        ("R-b", "99th percentile of $\\delta_{\\mathrm{ack}}$ without run-to-parity at most $2/3$",
         _ratio_cell((b, rb[b]["off"] / rb[b]["on"]) for b in both), r["R-b"]["verdict"]),
        ("P-a", "$W_{\\mathrm{so}}$ rises $0.9$--$1.1$~ms per ms added",
         "; ".join("\\%s{} $%.2f$" % (b, pa[b]["slope_ms_per_ms"]) for b in both),
         p["P-a"]["verdict"]),
        ("P-b", "$A$ moves at most $10\\%$ between delays",
         "; ".join("\\%s{} $%.0f\\%%$" % (b, 100.0 * pb[b]["move"]) for b in both),
         p["P-b"]["verdict"]),
        ("P-c", "$D$ rises $0.9$--$1.1$~ms per ms added",
         "; ".join("\\%s{} $%.2f$" % (b, pc[b]["slope_ms_per_ms"]) for b in both),
         p["P-c"]["verdict"]),
        ("L-a", "median $|W_{\\mathrm{so}} - W|$ at most $20\\,\\mu$s at every rung",
         "largest median $%.1f\\,\\mu$s" % max(c["median_us"] for c in l["L-a"]["checks"]),
         l["L-a"]["verdict"]),
        ("L-b", "$W_{\\mathrm{so}}$ within $10\\%$ under $88\\%$ load",
         "; ".join("%d/s \\%s{} $%+.1f\\%%$" % (c["rate"], c["backend"],
                                                 100.0 * (c["busy"] - c["idle"]) / c["idle"])
                   for c in held), l["L-b"]["verdict"]),
        ("L-c", "at 50/s, at most $1\\%$ of messages flagged",
         "at most $%.2f\\%%$" % (100.0 * max(c["flagged_share"] for c in l["L-c"]["checks"])),
         l["L-c"]["verdict"]),
        ("I", "\\texttt{idle=poll} halves \\redis{}'s share of $S$ in $[-250, -150)\\,\\mu$s",
         "$%.1f\\%%$ to $%.1f\\%%$" % (100.0 * i["I"]["decision"]["bump_share_default"],
                                     100.0 * i["I"]["decision"]["bump_share_poll"]), "decision"),
    ]
    lines = [
        "% Generated by scripts/emit_paper_numbers.py, through scripts/order_scope_numbers.py, from",
        "% docs/results/order_scope/*_runs.csv and scripts/order_scope.py's judges. Do not edit.",
        "\\begin{tabular}{@{}l>{\\raggedright\\arraybackslash}p{0.36\\columnwidth}"
        ">{\\raggedright\\arraybackslash}p{0.40\\columnwidth}l@{}}",
        "\\toprule",
        "& Required & The runs gave & Verdict \\\\",
        "\\midrule",
    ]
    lines += ["%s & %s & %s & %s \\\\" % row for row in rows]
    lines += ["\\bottomrule", "\\end{tabular}", ""]
    return "\n".join(lines)
