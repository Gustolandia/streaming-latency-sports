"""The broker audit's numbers for the paper's Section V-D and its broker table (tab:brokers), for
Supplement S7, and for the sizes of Section VI-C.

Reads the audit's committed record under data/broker_audit/: the coded brokers (batch_*.json),
the precedents (precedents.json), the population of products found (candidates.json) and the
search log (search_log.json). Every verdict comes from scripts/broker_audit.py, the rules the
audit's protocol and its amendment registered, so no count here is typed or stored.

It returns ledger macros, (name, value) pairs. scripts/emit_paper_numbers.py writes them into
docs/generated/paper_numbers.tex, so its --check holds them like every other number. A count that
is small enough is also given as a word, as IEEE style prints it in prose.
"""
import collections
import glob
import json
import os

import broker_audit

DIR = os.path.join("data", "broker_audit")

#: The words IEEE style prints for a small count; above twelve it takes the digits.
SPELLED = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
           "eleven", "twelve")

#: How a resolution the records give begins when it is finer than a millisecond: nanoseconds,
#: microseconds, units of 100 ns, or Zenoh's NTP64 stamps (2^-28 s).
FINER_THAN_MS = ("ns", "µs", "us", "100 ns", "ntp64")


def spell(n):
    return SPELLED[n] if 0 <= n < len(SPELLED) else str(n)


def thousands(n):
    """1302 -> 1{,}302, the ledger's way of writing a thousands separator."""
    return "{:,}".format(int(n)).replace(",", "{,}")


def base(said):
    """A verdict without its "(unless ...)" note."""
    return said.split(" (unless")[0]


def _json(root, name):
    with open(os.path.join(root, DIR, name), encoding="utf-8") as fh:
        return json.load(fh)


def records(root="."):
    """(brokers, precedents) of the record under `root`, each as broker_audit loads them."""
    batches = sorted(glob.glob(os.path.join(root, DIR, "batch_*.json")))
    if not batches:
        raise ValueError("no batch file under %s" % os.path.join(root, DIR))
    path = os.path.join(root, DIR, "precedents.json")
    return (broker_audit.load(batches),
            broker_audit.load_precedents([path]) if os.path.exists(path) else [])


def finer_than_ms(resolution):
    """Whether a resolution the record gives is finer than a millisecond."""
    return str(resolution or "").strip().lower().startswith(FINER_THAN_MS)


def fine_stays(brokers):
    """The brokers that hand a consumer both ends of the message's residence time, its arrival and
    its send, each finer than a millisecond."""
    out = set()
    for _, b in brokers:
        for m in b["modes"]:
            if base(broker_audit.verdict(m)) != "stay in the message":
                continue
            arrival = m["Q1"]["answer"] in broker_audit.STAMPED and m["Q2"]["answer"] == "yes"
            sent = m["Q3"]["answer"] == "send time" and m["Q4"]["answer"] == "yes"
            if arrival and sent and finer_than_ms(m["Q1"].get("resolution")) \
                    and finer_than_ms(m["Q3"].get("resolution")):
                out.add(b["broker"])
    return sorted(out)


def varint_limits(sizes=(1, 2, 3)):
    """For each size in bytes, the first wait in microseconds that no longer fits it, written as a
    base-128 variable-length integer: seven bits of the value in each byte."""
    return [(n, 128 ** n) for n in sizes]


def macros(root="."):
    """The ledger macros of Section V-D, its broker table and Supplement S7, and Section VI-C's
    sizes. The table prints a count in digits and the prose in words, so a small count is given
    both ways."""
    brokers, precedents = records(root)
    modes = [(b, m) for _, b in brokers for m in b["modes"]]
    producers = [p for _, b in brokers for p in b["producers"]]
    said = collections.Counter(base(broker_audit.verdict(m)) for _, m in modes)
    acked = collections.Counter(base(broker_audit.ack_verdict(p)) for p in producers)
    waits = collections.Counter(broker_audit.requests_wait(m) for _, m in modes)
    stays = {b["broker"] for b, m in modes if base(broker_audit.verdict(m)) == "stay in the message"}
    by_broker = collections.defaultdict(set)
    for b, m in modes:
        by_broker[b["broker"]].add(base(broker_audit.verdict(m)))
    kept = [(b["broker"], m) for b, m in modes
            if m["Q3"]["answer"] == "request arrival" and m["Q4"]["answer"] == "no"]
    kept_sends = [b["broker"] for b, m in modes
                  if m["Q3"]["answer"] == "send time" and m["Q4"]["answer"] == "no"]
    groups = collections.Counter(b["group"] for _, b in brokers)
    found = collections.Counter(
        "seed" if any(f["route"] == "seed" for f in b["found_by"]) else "search"
        for _, b in brokers if b["group"] == "C")
    products = _json(root, "candidates.json")["products"]
    decided = collections.Counter(p["decision"] for p in products)
    searches = _json(root, "search_log.json")["searches"]
    parts = [m for _, m in modes] + producers
    readings = [r for part in parts for r in part["read_back"]]
    # The answers to the registered questions (Q1-Q7, P1-P3), as the README counts them.
    questions = sorted(broker_audit.ANSWERS) + sorted(broker_audit.PRODUCER_ANSWERS)
    changed = [q for part in parts for q in questions
               if q in part and "changed_on_read_back" in part[q]]
    # A residence time known only from a duration in whole seconds: no send time handed on with
    # the arrival, and the duration counted in seconds (MQTT 5.0's expiry, for most of them).
    # 3 Nov 2026: a duration the records code as a stay counts as well as a derivable one, so
    # gmqtt's two MQTT 5.0 interfaces are in (36 became 38; the README's corrections say so).
    seconds = sum(1 for _, m in modes if base(broker_audit.verdict(m)) == "stay in the message"
                  and not (m["Q3"]["answer"] == "send time" and m["Q4"]["answer"] == "yes")
                  and m["Q5"]["answer"] in ("derivable stay", "stay")
                  and m["Q5"].get("resolution") == "s")
    quotes = sum(1 for _ in broker_audit.every_quote(brokers, precedents))
    return [
        ("baBrokers", str(len(brokers))),
        ("baFirstBrokers", str(groups["A"] + groups["B"])),
        ("baToolBrokers", str(groups["A"])),
        ("baCloudServicesWord", spell(groups["B"])),
        ("baSeedBrokers", str(found["seed"])),
        ("baSearchBrokers", str(found["search"])),
        ("baConsumerModes", str(len(modes))),
        ("baProducerModes", str(len(producers))),
        ("baWaitModesWord", spell(said["wait in the message"])),
        ("baWaitModes", str(said["wait in the message"])),
        ("baStayModes", str(said["stay in the message"])),
        ("baStayBrokers", str(len(stays))),
        ("baStaySecondModes", str(seconds)),
        ("baArrivalModes", str(said["arrival only"])),
        ("baNothingModes", str(said["nothing"])),
        ("baNothingBrokers", str(sum(1 for v in by_broker.values() if v == {"nothing"}))),
        ("baKeptRequestModes", str(len(kept))),
        ("baKeptRequestBrokers", str(len({name for name, _ in kept}))),
        ("baKeptRequestNsWord", spell(sum(
            1 for _, m in kept if str(m["Q3"].get("resolution", "")).startswith("ns")))),
        ("baKeptSendModes", str(len(kept_sends))),
        ("baKeptSendBrokers", str(len(set(kept_sends)))),
        ("baWaitCan", str(waits["yes"])),
        ("baWaitCannot", str(waits["no"])),
        ("baWaitUnsettledWord", spell(waits["not determined"])),
        ("baHoldModesWord", spell(acked["hold in the acknowledgment"])),
        ("baHoldModes", str(acked["hold in the acknowledgment"])),
        ("baOneTimeModes", str(acked["receive time only"] + acked["send time only"])),
        ("baReceiveOnlyModes", str(acked["receive time only"])),
        ("baSendOnlyModesWord", spell(acked["send time only"])),
        ("baNoTimeModes", str(acked["nothing"])),
        ("baNoAckModes", str(acked["no acknowledgment"])),
        ("baProducts", thousands(len(products))),
        ("baOut", str(decided["out"])),
        ("baCopies", str(decided["copy"])),
        ("baScreenedOut", str(decided["screened out"])),
        ("baNotChecked", str(decided["not checked"])),
        ("baNotReadableWord", spell(decided["not readable"])),
        ("baSearches", str(len(searches))),
        ("baQuotes", thousands(quotes)),
        ("baPrecedents", str(len(precedents))),
        ("baReadBacks", str(len(readings))),
        ("baReadBackDisagree", str(sum(1 for r in readings if not r["agrees"]))),
        ("baChangedOnReadBack", str(len(changed))),
        ("baNotDetermined", str(sum(len(part["not_determined"]) for part in parts))),
    ] + [("baVarint%sUs" % ("One", "Two", "Three")[n - 1], thousands(limit))
         for n, limit in varint_limits()]
