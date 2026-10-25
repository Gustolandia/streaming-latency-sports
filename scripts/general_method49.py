#!/usr/bin/env python3
"""
general_method49.py -- freeze 46's judge (plan version 49, docs/results/general_method/
DESIGN49.md): the remedy by protocol, judged on new runs by what it changes.

Version 47's verdicts stand (docs/results/general_method/README.md, "The verdicts"). Where requests
waited, W's tail held still; but V-a and N-a read the load's reach into the application as D's
on/off ratio over W's top 1%, the messages the remedy leaves slowest in the network, and D grew
there 1.14 to 1.47 times, short of 1.5, while D's own tail grew 2.7 to 6.5 times. On Kafka, W moved
with F, the broker's side, so KC-d could not show what the broker thread's priority changes. On
RabbitMQ the checks of B failed on its deliveries' pauses of 13 to 20 ms. This version judges five
blocks, on new runs:

  R (Redis, x86): at depth 1 the load opens the gap; at depth 256 a request waits for each message,
      W's tail is held still while D's own tail grows, and at most LEFT of depth 1's rise of W's
      tail is left, in size;
  J (NATS, x86): at depth 256 and with nats.go, a request waits for each message, and W's tail is
      held still while D's own tail grows. No setup of NATS opens the gap without falling behind
      (version 47's M3-b), so J does not measure how much of a gap the remedy removes;
  G (RabbitMQ, x86): at a prefetch of 1,000, a credit waits for each message, certified at the
      bound CERTIFY_B_WIDE_MS, and W's tail is held still while D's own tail grows; as for J, no
      gap is measured;
  Q (Kafka, x86): the client's part of the latency, W - F, grows under the load with librdkafka at
      normal priority; with only its broker thread at real-time priority what is left of that rise
      is at most LEFT of it, in size, and at most the check's resolution; and at least half of the
      messages still find no fetch waiting, the round trip being the protocol's latency;
  Z (Kafka, the Arm pair): Q's first two predictions again.

Each run's row is scripts/general_method.py's read_run's. Among its fields, this judge reads:
  W_ratio, W_rise           W's tail mean over its top 1% in each load state, on over off, and on
                            less off;
  D_own_ratio               D's mean over its own top 1% in each state, on over off: the load's
                            reach into the application, read over the messages it slows most there;
  WF_own_ratio, WF_own_rise the client's part, W - F per message (on Kafka min(T_c, S)), its mean
                            over its own top 1% in each state, on over off and on less off; a delay
                            on the broker's side can raise it only up to the client's own
                            turnaround, timed on the client host from the previous answer's last
                            byte to the next request;
  broker_waiting_share, broker_unwaited_share_on and _off, the broker's record of what each
                            message found;
  certified_share, b_checks and their _2ms and _50ms twins, the clients' certification and the
                            run's checks of B at each bound;
  m1b_missed, m1b_differ, order_differ, cap_certain_false_none, the instrument's own checks
                            (version 47's M1-b and M2-a), run by run.
Beside the held-still predictions it describes, in each load state, the parts of W the load could
move the other way: the card's lag Q (Q_own_*), the broker's residence (Res_own_*), and the share
of time the consumer's thread waited for a core (rq_share_*), which W cannot change.

The judge follows general_method.py's: a cell is one setup, or one comparison of two, in one block;
a setup's value is the median over its passing runs; a cell missing a value it needs is out of
reach, reported and not judged; and a cell that rests on another that did not hold is not judged.
A block's rows are those of its own pair only, Z's from the Arm pair and the others' from x86; a
run whose instrument's checks fail is left out, as a run that fails its integrity rule is; both
are listed. A setup the design runs that has no row left gives each prediction that reaches it an
out-of-reach cell.

The rounds are version 45's rule (scripts/general_method_power.py) through this judge, drawn about
version 47's judged runs of the setups this version repeats (FROM47), read by the same read_run.
One departure: whether a prediction clears its margin is judged on those runs themselves, four of
each setup, where the rule judges each setup's means twice, which would take each run's checks of
B from its first run alone.

CLI:
    python scripts/general_method49.py read --runs FOLDER [--runs ...] --driver IP --broker IP \\
        --receiver IP --allowance JSON --out-runs CSV [--workers N]
    python scripts/general_method49.py judge --runs-table CSV [--runs-table ...] --out JSON \\
        [--draws N]
    python scripts/general_method49.py power --runs-table CSV [--runs-table ...] [--rounds 4] \\
        [--most 12] [--blocks 2000] [--seed 20261104] [--spread rule|pilot] [--out JSON]
"""
import argparse
import json
import os
import random
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import general_method as gm  # noqa: E402
import general_method_power as gp  # noqa: E402
import order_scope as osc  # noqa: E402
import recv_wait as rw  # noqa: E402
import under_load as ul  # noqa: E402
import under_load_posthoc as ph  # noqa: E402

# --- the blocks ----------------------------------------------------------------------------------

#: This version's blocks; the one on the Arm pair.
BLOCKS = ("R", "J", "G", "Q", "Z")
ARM_BLOCK = "Z"

#: The predictions, as judge() names them, and the setups the design runs for each: a prediction
#: whose setup has no run left is out of reach there.
PREDICTIONS = ("R-a", "R-b", "R-c", "R-d", "J-a", "J-b", "G-a", "G-b", "Q-a", "Q-b", "Q-c", "Z-a",
               "Z-b")
REACHES = {"R-a": ("R2000-redis-d1",), "R-b": ("R2000-redis-d256",),
           "R-c": ("R2000-redis-d256",), "R-d": ("R2000-redis-d256",),
           "J-a": ("J2000-nats-d256", "J2000-nats-go"), "J-b": ("J2000-nats-d256", "J2000-nats-go"),
           "G-a": ("G2000-rabbitmq-p1000",), "G-b": ("G2000-rabbitmq-p1000",),
           "Q-a": ("Q2000-kafka-rdk",), "Q-b": ("Q2000-kafka-rdk-rt",),
           "Q-c": ("Q2000-kafka-rdk-rt",), "Z-a": ("Z2000-kafka-rdk",),
           "Z-b": ("Z2000-kafka-rdk-rt",)}
#: R-d, Q-b and Z-b compare the remedy's setup with the gap's, which must have runs too.
AGAINST = {"R-d": "R2000-redis-d1", "Q-b": "Q2000-kafka-rdk", "Z-b": "Z2000-kafka-rdk"}

#: Version 47's runs of the setups this version repeats, by this version's ids: the values the
#: rounds rule draws about. Every one ran in version 47's judged blocks with the duty, broker and
#: captures it runs with here, and with version 48's kit, which leaves these setups as version 47
#: ran them.
FROM47 = {"V2000-redis-d1": "R2000-redis-d1", "V2000-redis-d256": "R2000-redis-d256",
          "N2000-nats-d256": "J2000-nats-d256", "N2000-nats-go": "J2000-nats-go",
          "P2000-rabbitmq-p1000": "G2000-rabbitmq-p1000",
          "K2000-kafka-rdk": "Q2000-kafka-rdk", "K2000-kafka-rdk-rt": "Q2000-kafka-rdk-rt",
          "A2000-kafka-rdk": "Z2000-kafka-rdk", "A2000-kafka-rdk-rt": "Z2000-kafka-rdk-rt"}

# --- the predictions' margins (DESIGN49.md) ------------------------------------------------------

#: R-a and Q-a (and Z-a): the least on/off ratio that shows the load opened the gap, W's tail at
#: depth 1 and the client's part's own tail at normal priority. R-c, J-b and G-b: the least on/off
#: ratio of D's own tail that shows the load reached the application, and W held still within
#: 1/HOLDS_STILL and HOLDS_STILL by the equivalence test.
GROWTH = gm.GROWTH
HOLDS_STILL = gm.HOLDS_STILL
#: R-b, J-a and G-a, as M2-c: the least share of messages the broker's record shows found a
#: request or credit waiting, and the least share the clients' own timestamps certify, at each
#: block's bound B (the suffix of read_run's fields at that bound): CERTIFY_B_MS on Redis and NATS,
#: as version 47, and CERTIFY_B_WIDE_MS on RabbitMQ.
WAITING = gm.M2C_WAITING
CERTIFIED = gm.M2C_CERTIFIED
BOUND = {"R": "", "J": "", "G": "_50ms"}
BOUND_MS = {"": gm.CERTIFY_B_MS, "_50ms": gm.CERTIFY_B_WIDE_MS}
#: R-d, Q-b and Z-b: the most the remedy's rise may be of the gap's, in size, setup against setup
#: in the same block, each the median over its runs; and for the client's part (Q-b, Z-b), the
#: most it may be in microseconds, the check's resolution, below which the check calls no message
#: unwaited.
LEFT = 0.1
LEFT_US = ph.RESOLUTION_US
#: Q-c, as KC-h's second clause: the least share of messages that found no fetch waiting, by the
#: broker's record, in each load state.
UNWAITED = gm.KC_H_UNWAITED
#: The setups: Redis's depths, RabbitMQ's prefetch.
GAP_DEPTH, WAITING_DEPTH, WAITING_PREFETCH = (gm.GAPPED_DEPTH, gm.WAITING_DEPTH,
                                              gm.WAITING_PREFETCH)

#: The fields described setup by setup, the median over its runs.
DESCRIBED = ("timed", "d_joined", "W_tail_on", "W_tail_off", "W_ratio", "W_rise", "F_tail_on",
             "F_tail_off", "F_ratio", "F_rise", "D_ratio", "D_own_tail_on", "D_own_tail_off",
             "D_own_ratio", "WF_tail_on", "WF_tail_off", "WF_own_tail_on", "WF_own_tail_off",
             "WF_own_ratio", "WF_own_rise", "WFc_own_tail_on", "WFc_own_tail_off",
             "WFc_own_ratio", "WFc_own_rise", "Tc_req_ratio", "waiting_W_ratio",
             "Q_own_tail_on", "Q_own_tail_off", "Q_own_ratio", "Res_own_tail_on",
             "Res_own_tail_off", "Res_own_ratio", "rq_share_on", "rq_share_off", "rq_ratio",
             "broker_waiting_share", "broker_unwaited_share_on", "broker_unwaited_share_off",
             "cap_certain_none_share", "cap_calibrated_none_share", "certified_share",
             "certified_share_2ms", "certified_share_50ms", "retransmitted", "zero_windows",
             "probe_max_us", "q_max_us", "silence_max_us", "nofetch_time_share",
             "kch_predicted", "g_us", "g_turnaround_us", "g_rest_us", "m1b_missed",
             "m1b_differ", "cap_certain_false_none")


# --- the runs judged -----------------------------------------------------------------------------

def instrument_holds(row):
    """Whether the run's instrument checks out, as version 47's M1-b and M2-a read it: the
    broker's ids pair every message the payload's ids pair, and none differently, the confirm and
    delivery orders agreeing on RabbitMQ; and the certain reading calls no message unwaited that
    the broker shows waiting. False where one fails, None where one cannot be read."""
    return gm._both(ul._holds(lambda a, b: a == 0 and b == 0, gm._f(row, "m1b_missed"),
                              gm._f(row, "m1b_differ")),
                    gm._f(row, "order_differ") in (None, 0.0),
                    ul._holds(lambda c: c == 0, gm._f(row, "cap_certain_false_none")))


def runs_judged(rows):
    """(the rows judged, [{run, setup, why}] for this version's rows left out): each block's rows
    from its own pair, Z's from the Arm pair and the others' from x86; never a pilot's; and only
    runs whose instrument checks out."""
    kept, left = [], []
    for r in rows:
        if r.get("block") not in BLOCKS:
            continue
        why = None
        if r.get("pilot"):
            why = "a pilot's run"
        elif (r.get("arch") == gm.ARM) != (r["block"] == ARM_BLOCK):
            why = "run on the other pair (%s)" % r.get("arch")
        elif instrument_holds(r) is not True:
            why = "its instrument does not check out (M1-b or M2-a: %s)" % instrument_holds(r)
        if why:
            left.append({"run": r.get("run"), "setup": r.get("setup"), "why": why})
        else:
            kept.append(r)
    return kept, left


# --- the setups' roles ---------------------------------------------------------------------------

def _gapped(row):
    """Redis at depth 1: each replacement request sent before the reply is read."""
    return row["block"] == "R" and gm._int(row.get("depth")) == GAP_DEPTH


def _waiting(row):
    """A setup that keeps requests or credit waiting: Redis and NATS at WAITING_DEPTH, nats.go, and
    RabbitMQ at WAITING_PREFETCH."""
    return ((row["block"] in ("R", "J") and gm._int(row.get("depth")) == WAITING_DEPTH)
            or (row["block"] == "J" and row.get("consumer") == gm.NATS_GO)
            or (row["block"] == "G" and gm._int(row.get("prefetch")) == WAITING_PREFETCH))


def _librdkafka(row):
    return row["block"] in ("Q", ARM_BLOCK) and row.get("consumer") == gm.LIBRDKAFKA


def _normal(row):
    """librdkafka with every thread at normal priority."""
    return _librdkafka(row) and not row.get("fetch_rt") and not row.get("priority")


def _fetch_rt(row):
    """librdkafka with only its broker thread at real-time priority."""
    return _librdkafka(row) and bool(row.get("fetch_rt"))


def _in_block(verdict, block):
    """A prediction's cells in one block alone, judged again."""
    return gm._judged([c for c in verdict["checks"] if c["block"] == block])


# --- the judgments -------------------------------------------------------------------------------

def judge_gap(rows):
    """R-a: at depth 1, W's tail on/off ratio is at least GROWTH: the load opens the gap in the
    block the remedy is judged in. Beside it: the rise, and D's own tail ratio."""
    checks = []
    for s, runs in gm._setups(rows, _gapped):
        w = gm._median_of(runs, "W_ratio")
        checks.append(gm._cell(s, runs, W_ratio=w, W_rise=gm._median_of(runs, "W_rise"),
                               D_own_ratio=gm._median_of(runs, "D_own_ratio"),
                               holds=ul._holds(lambda x: x >= GROWTH, w)))
    return gm._judged(checks)


def judge_waiting(rows):
    """R-b, J-a and G-a, M2-c's form: where requests or credit are kept waiting, the broker's
    record shows one waiting for at least WAITING of messages, and the clients' own timestamps
    certify one for at least CERTIFIED of them, at the block's bound B, the certified share the
    median over the runs whose checks of B hold there: a run whose checks fail, or cannot be read,
    leaves its client clause out of reach. Beside them: the share certified at the other bounds,
    the probes, each run's longest silence, and the estimate's share that found none."""
    checks = []
    for s, runs in gm._setups(rows, _waiting):
        suffix = BOUND[runs[0]["block"]]
        waiting = gm._median_of(runs, "broker_waiting_share")
        share, each = gm._certified(runs, suffix)
        held = ul._holds(lambda w: w >= WAITING, waiting)
        certain = ul._holds(lambda c: c >= CERTIFIED, share)
        checks.append(gm._cell(s, runs, b_ms=BOUND_MS[suffix], waiting=waiting, certified=share,
                               runs_checked=[c for c, _ in each],
                               runs_certified=[x for _, x in each],
                               certified_10ms=gm._certified(runs)[0],
                               certified_2ms=gm._certified(runs, "_2ms")[0],
                               certified_50ms=gm._certified(runs, "_50ms")[0],
                               probes=sorted(set(str(r.get("probe_kind")) for r in runs)),
                               silence_max_us=[gm._f(r, "silence_max_us") for r in runs],
                               estimate_none=gm._median_of(runs, "cap_calibrated_none_share"),
                               broker_held=held, client_held=certain,
                               holds=gm._both(held, certain)))
    return gm._judged(checks)


def _components(runs):
    """Described beside a held-still W: the on/off ratios of the parts of W the load could move the
    other way, the card's lag Q and the broker's residence, each over its own top 1%, and whether
    both lie within 1/HOLDS_STILL and HOLDS_STILL; and the consumer thread's share of time waiting
    for a core in each state, which W cannot change."""
    q, res = gm._median_of(runs, "Q_own_ratio"), gm._median_of(runs, "Res_own_ratio")
    return {"Q_own_ratio": q, "Res_own_ratio": res,
            "parts_still": ul._holds(lambda a, b: all(1 / HOLDS_STILL <= x <= HOLDS_STILL
                                                      for x in (a, b)), q, res),
            "rq_share_on": gm._median_of(runs, "rq_share_on"),
            "rq_share_off": gm._median_of(runs, "rq_share_off")}


def _still(runs, judged):
    """W's tail held still over all messages, by the equivalence test across the runs' on/off
    ratios, while the median of D's own tail ratio is at least GROWTH; beside them the plain
    ratio, W's ratio over the messages that found one waiting, D's ratio over W's top 1% (version
    47's reading, which these runs are not judged by), and W's parts (_components)."""
    ratios = [gm._f(r, "W_ratio") for r in runs]
    still, p = gm.holds_still(ratios) if judged else (None, None)
    d = gm._median_of(runs, "D_own_ratio")
    grew = ul._holds(lambda x: x >= GROWTH, d) if judged else None
    return {"W_ratio": gm._median(ratios), "tost_p": p, "W_held_still": still,
            "D_own_ratio": d, "D_grew": grew,
            "waiting_W_ratio": gm._median_of(runs, "waiting_W_ratio"),
            "D_ratio": gm._median_of(runs, "D_ratio"), "parts": _components(runs),
            "holds": gm._both(still, grew) if judged else None}


def judge_still(rows, waiting):
    """R-c, J-b and G-b: where the setup's R-b, J-a or G-a cell holds, W's tail is held still while
    D's own tail grows (_still). A cell whose waiting did not hold is not judged."""
    held = dict((c["setup"], c["holds"]) for c in waiting["checks"])
    checks = []
    for s, runs in gm._setups(rows, _waiting):
        judged = held.get(s) is True
        checks.append(gm._cell(s, runs, judged=judged, **_still(runs, judged)))
    return gm._judged(checks)


def left_share(remedy, gap, field):
    """The remedy setup's median `field` over the gap setup's; None where either is missing or the
    gap's is not above zero."""
    a, b = gm._median_of(remedy, field), gm._median_of(gap, field)
    return None if None in (a, b) or b <= 0 else a / b


def left_interval(remedy, gap, field, draws, seed=gm.BOOTSTRAP_SEED):
    """(low, high, draws without a value): left_share with each setup's runs resampled with
    replacement, each run's two states together, the central INTERVAL of the values that came
    out; None, None where none did."""
    rng = random.Random(seed)
    found = []
    for _ in range(draws):
        value = left_share([rng.choice(remedy) for _ in remedy], [rng.choice(gap) for _ in gap],
                           field)
        if value is not None:
            found.append(value)
    if not found:
        return None, None, draws
    return (rw.percentile(found, 100 * (1 - gm.INTERVAL) / 2),
            rw.percentile(found, 100 * (1 + gm.INTERVAL) / 2), draws - len(found))


def judge_left(rows, gap_test, remedy_test, field, gap_verdict, draws, remedy_verdict=None,
               most_us=None):
    """R-d, Q-b and Z-b: the remedy setup's median rise of `field` is at most LEFT of the gap
    setup's in the same block, in size, a fall counting as a rise; and, where `most_us` is given,
    at most that many microseconds in size. A run-level interval of the share is beside it. Judged
    where the gap setup's cell of `gap_verdict` holds, and where `remedy_verdict` is given, the
    remedy setup's cell of it too; else not judged."""
    gap_held = dict((c["setup"], c["holds"]) for c in gap_verdict["checks"])
    remedy_held = dict((c["setup"], c["holds"]) for c in (remedy_verdict or {}).get("checks", []))
    checks = []
    for g, gaps in gm._setups(rows, gap_test):
        for s, runs in gm._setups(rows, remedy_test):
            judged = gap_held.get(g) is True and (remedy_verdict is None
                                                  or remedy_held.get(s) is True)
            share = left_share(runs, gaps, field) if judged else None
            rise = gm._median_of(runs, field)
            low, high, undefined = (left_interval(runs, gaps, field, draws)
                                    if judged and draws else (None, None, None))
            small = (ul._holds(lambda x: abs(x) <= most_us, rise) if most_us is not None
                     else True)
            checks.append(gm._cell(s, runs, against=g, judged=judged, rise=rise,
                                   rise_against=gm._median_of(gaps, field), left=share, low=low,
                                   high=high, undefined_draws=undefined, most_us=most_us,
                                   holds=gm._both(ul._holds(lambda x: abs(x) <= LEFT, share),
                                                  small) if judged else None))
    return gm._judged(checks)


def judge_client_part(rows):
    """Q-a and Z-a: with librdkafka at normal priority, the client's part's own tail on/off ratio
    is at least GROWTH: the load opens the client's part in the block the remedy is judged in.
    Beside it: its own tail in each state and its rise, the turnaround's own tail ratio, and the
    same part from the clients' timestamps alone (W - Fc)."""
    checks = []
    for s, runs in gm._setups(rows, _normal):
        ratio = gm._median_of(runs, "WF_own_ratio")
        checks.append(gm._cell(s, runs, WF_own_ratio=ratio,
                               WF_own_tail_on=gm._median_of(runs, "WF_own_tail_on"),
                               WF_own_tail_off=gm._median_of(runs, "WF_own_tail_off"),
                               WF_own_rise=gm._median_of(runs, "WF_own_rise"),
                               Tc_req_ratio=gm._median_of(runs, "Tc_req_ratio"),
                               WFc_own_ratio=gm._median_of(runs, "WFc_own_ratio"),
                               holds=ul._holds(lambda x: x >= GROWTH, ratio)))
    return gm._judged(checks)


def judge_round_trip(rows):
    """Q-c, as KC-h's second clause: with only librdkafka's broker thread at real-time priority,
    in both load states at least UNWAITED of the messages found no fetch waiting, by the broker's
    record. Beside it: the share of time no fetch waited at the broker, the model's share, and the
    gap at the broker with its split."""
    checks = []
    for s, runs in gm._setups(rows, _fetch_rt):
        on, off = (gm._median_of(runs, "broker_unwaited_share_" + state) for state in gm.STATES)
        checks.append(gm._cell(s, runs, unwaited_on=on, unwaited_off=off,
                               holds=ul._holds(lambda a, b: min(a, b) >= UNWAITED, on, off),
                               described=dict((field, gm._median_of(runs, field)) for field in (
                                   "nofetch_time_share", "kch_predicted", "g_us",
                                   "g_turnaround_us", "g_rest_us"))))
    return gm._judged(checks)


def with_missing(verdict, prediction, present):
    """The prediction judged again with an out-of-reach cell for each setup it reaches that has no
    run, or whose gap setup has none, among `present`."""
    have = set(c["setup"] for c in verdict["checks"])
    missing = [s for s in REACHES[prediction] if s not in have and (
        s not in present or AGAINST.get(prediction, s) not in present)]
    if not missing:
        return verdict
    return gm._judged(verdict["checks"] + [{"setup": s, "block": s[0], "runs": 0, "holds": None,
                                            "why": "no passing run"} for s in missing])


def described(rows):
    """Medians over each setup's runs of what the predictions do not judge, or judge elsewhere."""
    out = []
    for s, runs in gm._setups(rows, lambda r: True):
        entry = gm._cell(s, runs)
        entry.update((field, gm._median_of(runs, field)) for field in DESCRIBED)
        out.append(entry)
    return out


def judge(rows, draws=gm.BOOTSTRAP):
    """Every prediction of this version over the run rows judged (runs_judged); the round trip on
    the Arm pair described beside them, and the runs left out listed."""
    rows, left = runs_judged(rows)
    block = dict((b, [r for r in rows if r["block"] == b]) for b in BLOCKS)
    out = {"R-a": judge_gap(block["R"])}
    waiting = judge_waiting(rows)
    still = judge_still(rows, waiting)
    for (named, b), (stilled, _) in zip((("R-b", "R"), ("J-a", "J"), ("G-a", "G")),
                                        (("R-c", "R"), ("J-b", "J"), ("G-b", "G"))):
        out[named], out[stilled] = _in_block(waiting, b), _in_block(still, b)
    out["R-d"] = judge_left(block["R"], _gapped, _waiting, "W_rise", out["R-a"], draws,
                            out["R-b"])
    for b in ("Q", ARM_BLOCK):
        out[b + "-a"] = judge_client_part(block[b])
        out[b + "-b"] = judge_left(block[b], _normal, _fetch_rt, "WF_own_rise", out[b + "-a"],
                                   draws, most_us=LEFT_US)
    out["Q-c"] = judge_round_trip(block["Q"])
    present = set(r["setup"] for r in rows)
    for p in PREDICTIONS:
        out[p] = with_missing(out[p], p, present)
    out["described"] = {"setups": described(rows), "left_out": left,
                        "round_trip_arm": judge_round_trip(block[ARM_BLOCK])["checks"]}
    return out


# --- the rounds ----------------------------------------------------------------------------------

#: The tail means the predictions read, drawn in each made-up run; and the run's checks of B at
#: each bound, drawn from version 47's runs of the setup, one of its runs at random.
TAILS = ("W", "D_own", "WF_own")
CHECKS = ("b_checks", "b_checks_2ms", "b_checks_50ms")


def from47(rows):
    """{this version's setup: version 47's runs of it, renamed}: each run's setup and block as
    this version names them."""
    out = {}
    for r in rows:
        name = FROM47.get(r.get("setup"))
        if name is not None and not r.get("pilot"):
            out.setdefault(name, []).append(dict(r, setup=name, block=name[0]))
    return dict(sorted(out.items()))


def profiles(runs47):
    """{setup: (base, spreads, runs)}: general_method_power's profile of each setup's runs."""
    return dict((s, gp.profile(runs) + (runs,)) for s, runs in runs47.items())


def made_up_block(rng, found, rounds, mode="rule", scale=1.0):
    """`rounds` made-up runs of every setup, as general_method_power draws them, with this
    version's tails, and each run's checks of B those of one of the setup's runs at random."""
    ratio_cv = (gp.ratio_spreads(dict((s, p[:2]) for s, p in found.items()), TAILS)
                if mode == "pilot" else None)
    rows = []
    for _, (base, cv, runs) in found.items():
        for i in range(rounds):
            run = gp.made_up_run(rng, base, cv, i, mode, ratio_cv, scale, TAILS)
            for name in CHECKS:
                run[name] = rng.choice([r.get(name) for r in runs])
            rows.append(run)
    return rows


def verdicts(rows):
    """{prediction: its verdict} from this judge; no interval is drawn, since none decides a
    verdict."""
    out = judge(rows, draws=0)
    return dict((p, out[p]["verdict"]) for p in PREDICTIONS)


def clears(runs47):
    """{prediction: whether the judge confirms it on version 47's own runs of the setups}."""
    return dict((p, v == gp.CONFIRMED) for p, v in verdicts(
        [r for runs in runs47.values() for r in runs]).items())


def power(found, rounds, blocks, seed, mode="rule", scale=1.0):
    """{prediction: share of `blocks` made-up blocks the judge confirms it in}."""
    rng = random.Random(seed)
    counts = dict.fromkeys(PREDICTIONS, 0)
    for _ in range(blocks):
        for p, v in verdicts(made_up_block(rng, found, rounds, mode, scale)).items():
            counts[p] += v == gp.CONFIRMED
    return dict((p, counts[p] / float(blocks)) for p in PREDICTIONS)


def rounds_needed(runs47, blocks, seed, start=4, most=12, mode="rule"):
    """Version 45's rule through this judge (general_method_power.rounds_needed)."""
    return gp.rounds_needed(profiles(runs47), blocks, seed, start, most, mode, power_of=power,
                            clear=clears(runs47), predictions=PREDICTIONS)


# --- files ---------------------------------------------------------------------------------------

def _read_one(job):
    path, driver, broker, receiver, allowance, warmup_s = job
    return gm.read_run(path, driver, broker, receiver, allowance, warmup_s)


def read_block(folders, driver, broker, receiver, allowance, warmup_s=gm.WARMUP_S, workers=1):
    """(one row per passing run of this version's blocks, [(run, verdict)] for the runs left
    out): general_method's read_run on each, `workers` at a time."""
    found, skipped = gm.block_runs(folders)
    jobs = [(path, driver, broker, receiver, allowance, warmup_s) for setup in sorted(found)
            if setup[0] in BLOCKS for path in found[setup]]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            return list(ex.map(_read_one, jobs)), skipped
    return [_read_one(job) for job in jobs], skipped


def read_tables(paths):
    rows = []
    for path in paths:
        rows.extend(gm.read_table(path))
    return rows


def _write_json(path, value):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(value, fh, indent=2, sort_keys=True)
        fh.write("\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("read")
    p.add_argument("--runs", action="append", required=True)
    for flag in ("--driver", "--broker", "--receiver", "--allowance", "--out-runs"):
        p.add_argument(flag, required=True)
    p.add_argument("--warmup", type=float, default=gm.WARMUP_S)
    p.add_argument("--workers", type=int, default=1)
    p = sub.add_parser("judge")
    p.add_argument("--runs-table", action="append", required=True)
    p.add_argument("--draws", type=int, default=gm.BOOTSTRAP)
    p.add_argument("--out", required=True)
    p = sub.add_parser("power")
    p.add_argument("--runs-table", action="append", required=True)
    p.add_argument("--rounds", type=int, default=4)
    p.add_argument("--most", type=int, default=12)
    p.add_argument("--blocks", type=int, default=2000)
    p.add_argument("--seed", type=int, default=20261104)
    p.add_argument("--spread", choices=("rule", "pilot"), default="rule")
    p.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    if args.cmd == "read":
        with open(args.allowance, encoding="utf-8") as fh:
            allowance = json.load(fh)
        rows, skipped = read_block(args.runs, args.driver, args.broker, args.receiver, allowance,
                                   args.warmup, args.workers)
        osc.write_csv(args.out_runs, rows)
        for run, verdict in skipped:
            print("left out %s: %s" % (run, verdict))
        print("OK %d runs of plan version 49 -> %s" % (len(rows), args.out_runs))
        return 0
    if args.cmd == "judge":
        out = judge(read_tables(args.runs_table), args.draws)
        _write_json(args.out, out)
        for name in PREDICTIONS:
            print("%s: %s" % (name, out[name]["verdict"]))
        for left in out["described"]["left_out"]:
            print("left out %s (%s): %s" % (left["run"], left["setup"], left["why"]))
        return 0
    runs47 = from47(read_tables(args.runs_table))
    if not runs47:
        print("ERROR: the tables hold no run of version 47's setups this version repeats",
              file=sys.stderr)
        return 1
    print("setups: %d, from %d of version 47's runs" % (len(runs47), sum(
        len(r) for r in runs47.values())))
    clear = clears(runs47)
    print("confirmed on version 47's own runs: %s" % ", ".join(
        "%s %s" % (p, "yes" if clear[p] else "no") for p in PREDICTIONS))
    rounds, at, wanted, unreachable = rounds_needed(runs47, args.blocks, args.seed, args.rounds,
                                                    args.most, args.spread)
    halved = power(profiles(runs47), rounds, args.blocks, args.seed, args.spread, 0.5)
    print("the rule asks %d rounds (%s spread): %s" % (rounds, args.spread, "  ".join(
        "%s %.3f" % (p, at[p]) for p in PREDICTIONS)))
    if unreachable:
        print("no number of rounds up to %d brings %s to %.2f" % (
            args.most, ", ".join(unreachable), gp.POWER))
    print("with the load's excess halved: %s" % "  ".join(
        "%s %.3f" % (p, halved[p]) for p in PREDICTIONS))
    if args.out:
        _write_json(args.out, {"rounds": rounds, "spread": args.spread, "blocks": args.blocks,
                               "seed": args.seed, "power": at, "power_excess_halved": halved,
                               "clears": clear, "wanted": wanted, "unreachable": unreachable,
                               "most": args.most, "bar": gp.POWER, "idle_cv": gp.IDLE_CV,
                               "load_cv": gp.LOAD_CV, "runs": dict(
                                   (s, sorted(r["run"] for r in runs))
                                   for s, runs in runs47.items())})
        print("OK -> %s" % args.out)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
