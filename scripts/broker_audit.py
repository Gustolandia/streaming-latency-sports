#!/usr/bin/env python3
"""
broker_audit.py -- the broker audit's records, the verdicts they lead to, and a fetch-back of every
quote they rest on.

The protocol is data/broker_audit/PROTOCOL.md, registered before any record was coded, and its
amendment 1 (AMENDMENT_01.md), registered before the wide search it adds was run. Each record says,
for one broker and each of its consumer interfaces, which times the broker keeps for a message and
which it hands the consumer, and for each of its producer interfaces, which times it puts in its
acknowledgment of a publish, with a quote from a pinned source for every answer. The verdicts are
not stored anywhere. They are computed here, from the answers, by the rules the protocol and the
amendment registered, so a reader who disagrees with a verdict can find the answer it came from.
The precedents (protocols outside the brokers that send the far end's times) are checked here too.

CLI:
    python scripts/broker_audit.py validate [FILE ...]   # the form of every record; offline
    python scripts/broker_audit.py table [FILE ...]      # the consumers' verdicts, as Markdown
    python scripts/broker_audit.py producers [FILE ...]  # the producers' verdicts, as Markdown
    python scripts/broker_audit.py check [FILE ...]      # fetch every URL and find every quote

With no FILE, it reads data/broker_audit/batch_*.json and data/broker_audit/precedents.json. `check`
needs the network and is not part of the test suite, for the reason scripts/check_upstream_lines.py
gives: a check whose answer depends on what a stranger changed this morning must not turn the build
red. Its exit status is 1 if any quote is missing or any fetch failed. A PDF is read as its text.
"""
import argparse
import glob
import html
import io
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORDS = os.path.join(ROOT, "data", "broker_audit", "batch_*.json")
PRECEDENTS = os.path.join(ROOT, "data", "broker_audit", "precedents.json")
AGENT = "Mozilla/5.0 (compatible; broker-audit-check/1.0)"

#: The answers each question allows (PROTOCOL.md, "The questions").
ANSWERS = {
    "Q1": ("always", "by configuration", "no", "not determined"),
    "Q2": ("yes", "no", "not applicable", "not determined"),
    "Q3": ("request arrival", "send time", "no", "not determined"),
    "Q4": ("yes", "no", "not applicable", "not determined"),
    "Q5": ("wait", "stay", "derivable wait", "derivable stay", "no", "not determined"),
    "Q6": ("per message", "per request", "aggregate only", "none", "not determined"),
    "Q7": ("standing", "credit or several", "one at a time", "none", "not determined"),
}
QUESTIONS = ("Q0",) + tuple(sorted(ANSWERS))
#: The answers each of the producer's questions allows (AMENDMENT_01.md, "The producer's
#: questions").
PRODUCER_ANSWERS = {
    "P1": ("always", "by configuration", "no", "not applicable", "not determined"),
    "P2": ("always", "by configuration", "no", "not applicable", "not determined"),
    "P3": ("hold", "derivable hold", "no", "not applicable", "not determined"),
}
PRODUCER_QUESTIONS = ("P0",) + tuple(sorted(PRODUCER_ANSWERS))
STAMPED = ("always", "by configuration")
WAITING = ("standing", "credit or several")
HELD = ("hold", "derivable hold")
#: Which time a receive time in an acknowledgment is.
WHICH = ("receive time", "store time")
GROUPS = ("A", "B", "C")
#: What a broker of group C is (AMENDMENT_01.md, "The records").
KINDS = ("broker", "streaming platform", "cloud service", "real-time service", "webhook service",
         "job-queue server", "database queue", "IoT hub", "standard")
#: How a broker of group C was found (AMENDMENT_01.md, "How brokers are found").
ROUTES = ("seed", "route 1", "route 2")
#: Branch names that move. A URL into a repository must name a tag or a commit instead.
MOVING = ("main", "master", "head", "trunk", "develop", "dev", "latest", "gh-pages")
QUOTE_MOST = 300


def _batches(paths, default, key):
    """Every item under `key` of every file, in file order, each with the file it came from."""
    out = []
    for path in paths or default():
        with open(path, encoding="utf-8") as fh:
            batch = json.load(fh)
        for entry in batch.get(key, []):
            out.append((path, entry))
    return out


def load(paths=None):
    """Every broker of every batch, in file order, each with the file it came from."""
    return _batches(paths, lambda: sorted(glob.glob(RECORDS)), "brokers")


def load_precedents(paths=None):
    """Every precedent, each with the file it came from."""
    return _batches(paths, lambda: [p for p in [PRECEDENTS] if os.path.exists(p)], "precedents")


def ref_of(url):
    """The branch, tag or commit a repository URL is pinned to, or None if it is not one."""
    m = re.match(r"https://raw\.githubusercontent\.com/[^/]+/[^/]+/([^/]+)/", url)
    if m is None:
        m = re.match(r"https://github\.com/[^/]+/[^/]+/(?:blob|tree|raw)/([^/]+)/", url)
    return m.group(1) if m else None


def evidence_faults(items, where):
    """What is wrong with one evidence list: its items' form, pinning and length."""
    faults = []
    for i, item in enumerate(items):
        at = "%s[%d]" % (where, i)
        if not isinstance(item, dict) or set(item) != {"url", "quote"}:
            faults.append("%s: an item is {url, quote}" % at)
            continue
        url, quote = item["url"], item["quote"]
        if not isinstance(url, str) or not url.startswith("https://"):
            faults.append("%s: the URL is not https" % at)
        elif (ref_of(url) or "").lower() in MOVING:
            faults.append("%s: the URL names the moving branch %r" % (at, ref_of(url)))
        if not isinstance(quote, str) or not quote.strip():
            faults.append("%s: the quote is empty" % at)
        elif len(quote) > QUOTE_MOST:
            faults.append("%s: the quote is longer than %d characters" % (at, QUOTE_MOST))
    return faults


def mode_faults(mode, where):
    """What is wrong with one mode's answers, against the protocol's form."""
    faults = []
    for q in QUESTIONS:
        if not isinstance(mode.get(q), dict):
            faults.append("%s: %s is missing" % (where, q))
    if faults:
        return faults
    if not mode["Q0"].get("fields"):
        faults.append("%s.Q0: the list of fields is empty" % where)
    if not mode["Q0"].get("evidence"):
        faults.append("%s.Q0: no evidence" % where)
    faults += evidence_faults(mode["Q0"].get("evidence") or [], where + ".Q0")
    for q in sorted(ANSWERS):
        answer = mode[q].get("answer")
        if answer not in ANSWERS[q]:
            faults.append("%s.%s: %r is not an answer the protocol allows" % (where, q, answer))
            continue
        items = mode[q].get("evidence") or []
        if not items and answer != "not applicable":
            faults.append("%s.%s: no evidence" % (where, q))
        faults += evidence_faults(items, "%s.%s" % (where, q))
    for stamp, delivered in (("Q1", "Q2"), ("Q3", "Q4")):
        if mode[stamp].get("answer") == "no" and mode[delivered].get("answer") != "not applicable":
            faults.append("%s.%s: with %s 'no', it is 'not applicable'" % (where, delivered, stamp))
        if (mode[delivered].get("answer") == "not applicable"
                and mode[stamp].get("answer") != "no"):
            faults.append("%s.%s: 'not applicable' only when %s is 'no'" % (where, delivered, stamp))
    if mode["Q1"].get("answer") in STAMPED and not mode["Q1"].get("resolution"):
        faults.append("%s.Q1: a stamp is recorded with its resolution" % where)
    for key in ("not_determined", "read_back"):
        if not isinstance(mode.get(key), list):
            faults.append("%s: %s is a list" % (where, key))
    return faults


def producer_faults(producer, where):
    """What is wrong with one producer interface's answers, against the amendment's form."""
    faults = []
    for q in PRODUCER_QUESTIONS:
        if not isinstance(producer.get(q), dict):
            faults.append("%s: %s is missing" % (where, q))
    if faults:
        return faults
    p0 = producer["P0"]
    acked = p0.get("acknowledgment")
    if not isinstance(acked, bool):
        faults.append("%s.P0: acknowledgment is true or false" % where)
    elif acked and not p0.get("fields"):
        faults.append("%s.P0: the list of fields is empty" % where)
    if not p0.get("evidence"):
        faults.append("%s.P0: no evidence" % where)
    faults += evidence_faults(p0.get("evidence") or [], where + ".P0")
    for q in sorted(PRODUCER_ANSWERS):
        answer = producer[q].get("answer")
        if answer not in PRODUCER_ANSWERS[q]:
            faults.append("%s.%s: %r is not an answer the amendment allows" % (where, q, answer))
            continue
        items = producer[q].get("evidence") or []
        if not items and answer != "not applicable":
            faults.append("%s.%s: no evidence" % (where, q))
        faults += evidence_faults(items, "%s.%s" % (where, q))
        if isinstance(acked, bool) and (answer == "not applicable") == acked:
            faults.append("%s.%s: 'not applicable' exactly when there is no acknowledgment"
                          % (where, q))
        if answer in STAMPED and not producer[q].get("resolution"):
            faults.append("%s.%s: a time is recorded with its resolution" % (where, q))
    if producer["P1"].get("answer") in STAMPED and producer["P1"].get("which") not in WHICH:
        faults.append("%s.P1: which is 'receive time' or 'store time'" % where)
    for key in ("not_determined", "read_back"):
        if not isinstance(producer.get(key), list):
            faults.append("%s: %s is a list" % (where, key))
    return faults


def found_by_faults(broker, where):
    """What is wrong with a group C broker's kind and the record of how it was found."""
    faults = []
    if broker.get("kind") not in KINDS:
        faults.append("%s: kind is one the amendment names" % where)
    found = broker.get("found_by") or []
    if not found:
        faults.append("%s: found_by is empty" % where)
    for i, item in enumerate(found):
        if (not isinstance(item, dict) or set(item) != {"route", "source", "query"}
                or item["route"] not in ROUTES):
            faults.append("%s.found_by[%d]: an item is {route, source, query}, on a route the "
                          "amendment names" % (where, i))
    return faults


def broker_faults(broker, where):
    """What is wrong with one broker's record."""
    faults = []
    for key in ("broker", "version"):
        if not isinstance(broker.get(key), str) or not broker[key].strip():
            faults.append("%s: %s is missing" % (where, key))
    if broker.get("group") not in GROUPS:
        faults.append("%s: group is A, B or C" % where)
    elif broker["group"] == "C":
        faults += found_by_faults(broker, where)
    if not broker.get("version_evidence"):
        faults.append("%s: the version has no evidence" % where)
    faults += evidence_faults(broker.get("version_evidence") or [], where + ".version_evidence")
    modes = broker.get("modes") or []
    if not modes:
        faults.append("%s: no modes" % where)
    for mode in modes:
        faults += mode_faults(mode, "%s/%s" % (where, mode.get("mode", "?")))
    producers = broker.get("producers") or []
    if not producers:
        faults.append("%s: no producers" % where)
    for producer in producers:
        faults += producer_faults(producer, "%s/%s" % (where, producer.get("interface", "?")))
    return faults


def precedent_faults(precedent, where):
    """What is wrong with one precedent's record."""
    faults = []
    for key in ("name", "standard", "split"):
        if not isinstance(precedent.get(key), str) or not precedent[key].strip():
            faults.append("%s: %s is missing" % (where, key))
    if not precedent.get("sends"):
        faults.append("%s: the list of what it sends is empty" % where)
    if not precedent.get("evidence"):
        faults.append("%s: no evidence" % where)
    faults += evidence_faults(precedent.get("evidence") or [], where + ".evidence")
    return faults


#: The answer to each of Q1 to Q5 that would let the message carry the most.
BEST = {"Q1": "always", "Q2": "yes", "Q3": "request arrival", "Q4": "yes", "Q5": "wait"}


def carried(a):
    """What the message carries (PROTOCOL.md, "The verdicts"), from answers keyed by question."""
    arrival = a["Q1"] in STAMPED and a["Q2"] == "yes"
    if (a["Q3"] == "request arrival" and a["Q4"] == "yes" and arrival) or a["Q5"] in (
            "wait", "derivable wait"):
        return "wait in the message"
    if (a["Q3"] == "send time" and a["Q4"] == "yes" and arrival) or a["Q5"] in (
            "stay", "derivable stay"):
        return "stay in the message"
    return "arrival only" if arrival else "nothing"


def verdict(mode):
    """What the message carries, and, where an answer was not determined and could change that,
    which ones could."""
    a = dict((q, mode[q]["answer"]) for q in ANSWERS)
    said = carried(a)
    open_ = [q for q in sorted(BEST) if a[q] == "not determined"]
    if carried(dict(a, **dict((q, BEST[q]) for q in open_))) != said:
        said += " (unless %s)" % ", ".join(open_)
    return said


def requests_wait(mode):
    answer = mode["Q7"]["answer"]
    if answer == "not determined":
        return "not determined"
    return "yes" if answer in WAITING else "no"


def broker_access(mode):
    answer = mode["Q6"]["answer"]
    if answer == "not determined":
        return "not determined"
    return "yes" if answer in ("per message", "per request") else "no"


def stamps(mode):
    """(in the message, kept at the broker only): each stamp and duration with its resolution,
    named as the record names it. What the broker keeps but does not send is what a broker could
    put in the message without measuring anything new."""
    sent, kept = [], []
    q1, q3, q5 = mode["Q1"], mode["Q3"], mode["Q5"]
    if q1["answer"] in STAMPED:
        name = "%s (%s, arrival%s)" % (q1.get("field") or "a stamp", q1.get("resolution", "?"),
                                       ", by configuration" if q1["answer"] == "by configuration"
                                       else "")
        (sent if mode["Q2"]["answer"] == "yes" else kept).append(name)
    if q3["answer"] in ("request arrival", "send time"):
        name = "%s (%s, %s)" % (q3.get("field") or "a stamp", q3.get("resolution", "?"),
                                q3["answer"])
        (sent if mode["Q4"]["answer"] == "yes" else kept).append(name)
    if q5["answer"] not in ("no", "not determined"):
        sent.append("%s (%s, %s)" % (q5.get("field") or "a duration", q5.get("resolution", "?"),
                                     q5["answer"]))
    return "; ".join(sent) or "none", "; ".join(kept) or "none"


#: The answer to each of P1 to P3 that would let the acknowledgment carry the most.
BEST_ACK = {"P1": "always", "P2": "always", "P3": "hold"}


def acknowledged(a):
    """What the acknowledgment carries (AMENDMENT_01.md, "The producer's verdict"), from answers
    keyed by question."""
    if a["P3"] in HELD or (a["P1"] in STAMPED and a["P2"] in STAMPED):
        return "hold in the acknowledgment"
    if a["P1"] in STAMPED:
        return "receive time only"
    return "send time only" if a["P2"] in STAMPED else "nothing"


def ack_verdict(producer):
    """What the acknowledgment carries, and, where an answer was not determined and could change
    that, which ones could."""
    if producer["P0"]["acknowledgment"] is False:
        return "no acknowledgment"
    a = dict((q, producer[q]["answer"]) for q in PRODUCER_ANSWERS)
    said = acknowledged(a)
    open_ = [q for q in sorted(BEST_ACK) if a[q] == "not determined"]
    if acknowledged(dict(a, **dict((q, BEST_ACK[q]) for q in open_))) != said:
        said += " (unless %s)" % ", ".join(open_)
    return said


def ack_times(producer):
    """Each time and duration in the acknowledgment, with its resolution, named as the record
    names it."""
    out = []
    for q in ("P1", "P2"):
        p = producer[q]
        if p["answer"] in STAMPED:
            out.append("%s (%s, %s%s)" % (
                p.get("field") or "a time", p.get("resolution", "?"),
                p.get("which") if q == "P1" else "send time",
                ", by configuration" if p["answer"] == "by configuration" else ""))
    p3 = producer["P3"]
    if p3["answer"] in HELD:
        out.append("%s (%s, %s)" % (p3.get("field") or "a duration", p3.get("resolution", "?"),
                                    p3["answer"]))
    return "; ".join(out) or "none"


def producer_table(brokers):
    """The producers' verdicts, one row per broker and producer interface."""
    rows = ["| Broker | Producer interface | Version | What the acknowledgment carries |"
            " Times in it |",
            "|---|---|---|---|---|"]
    for _, broker in brokers:
        for producer in broker.get("producers") or []:
            rows.append("| %s | %s | %s | %s | %s |" % (
                broker["broker"], producer["interface"], broker["version"],
                ack_verdict(producer), ack_times(producer)))
    return "\n".join(rows)


def table(brokers):
    """The verdicts, one row per broker and mode."""
    rows = ["| Broker | Mode | Version | What the message carries | In the message |"
            " Kept at the broker only | Requests wait | Broker access |",
            "|---|---|---|---|---|---|---|---|"]
    for _, broker in brokers:
        for mode in broker["modes"]:
            sent, kept = stamps(mode)
            rows.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
                broker["broker"], mode["mode"], broker["version"], verdict(mode), sent, kept,
                requests_wait(mode), broker_access(mode)))
    return "\n".join(rows)


# --- fetching back -------------------------------------------------------------------------------

def fetch(url, opener=None):
    """The text at a URL, or a PDF's text. `opener` is injected by the tests."""
    opener = opener or urllib.request.urlopen
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with opener(request, timeout=60) as response:
        data = response.read()
    return pdf_text(data) if data[:5] == b"%PDF-" else data.decode("utf-8", errors="replace")


def pdf_text(data, reader=None):
    """The text of a PDF, page after page. `reader` is injected by the tests."""
    if reader is None:
        from pypdf import PdfReader as reader
    return "\n".join(page.extract_text() or "" for page in reader(io.BytesIO(data)).pages)


def readings(text):
    """The ways a page can be read as plain text: as it is, and, if it is HTML, with its tags
    taken out and with each tag read as a space. White space is collapsed in each."""
    out = [text]
    if re.search(r"<(html|body|div|p|span|td|code|pre)\b", text, re.I):
        bare = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text)
        out.append(html.unescape(re.sub(r"<[^>]+>", "", bare)))
        out.append(html.unescape(re.sub(r"<[^>]+>", " ", bare)))
    return [" ".join(t.split()) for t in out]


def found(quote, text):
    """'exact' if the quote is in the text with white space collapsed, 'spacing' if only with
    white space ignored, otherwise None."""
    quote = " ".join(quote.split())
    texts = readings(text)
    if any(quote in t for t in texts):
        return "exact"
    squeezed = "".join(quote.split())
    if any(squeezed in "".join(t.split()) for t in texts):
        return "spacing"
    return None


def every_quote(brokers, precedents=()):
    """(where, url, quote) for every evidence item of every record and precedent."""
    for path, broker in brokers:
        name = os.path.basename(path) + ":" + broker.get("broker", "?")
        for item in broker.get("version_evidence") or []:
            yield name + ".version", item["url"], item["quote"]
        for key, label, questions in (("modes", "mode", QUESTIONS),
                                      ("producers", "interface", PRODUCER_QUESTIONS)):
            for part in broker.get(key) or []:
                for q in questions:
                    for item in (part.get(q) or {}).get("evidence") or []:
                        yield ("%s/%s.%s" % (name, part.get(label, "?"), q), item["url"],
                               item["quote"])
    for path, precedent in precedents:
        for item in precedent.get("evidence") or []:
            yield ("%s:%s" % (os.path.basename(path), precedent.get("name", "?")), item["url"],
                   item["quote"])


def check(brokers, get=fetch, precedents=()):
    """Fetch every URL once and look for every quote in it. Returns (lines, failures)."""
    pages, lines, failures = {}, [], 0
    for where, url, quote in every_quote(brokers, precedents):
        if url not in pages:
            try:
                pages[url] = get(url)
            except Exception as exc:  # any failure to fetch is reported, never skipped
                pages[url] = exc
        page = pages[url]
        if isinstance(page, Exception):
            outcome = "FETCH FAILED (%s)" % page.__class__.__name__
        else:
            how = found(quote, page)
            outcome = {"exact": "OK", "spacing": "OK (spacing)", None: "MISSING"}[how]
        if not outcome.startswith("OK"):
            failures += 1
        lines.append("%-14s %s  %s\n               %r" % (outcome, where, url, quote[:90]))
    return lines, failures


def main(argv=None, out=sys.stdout, get=fetch):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("validate", "table", "producers", "check"))
    parser.add_argument("files", nargs="*")
    args = parser.parse_args(argv)
    brokers, precedents = load(args.files), load_precedents(args.files)
    faults = []
    for path, broker in brokers:
        faults += broker_faults(broker, "%s:%s" % (os.path.basename(path),
                                                   broker.get("broker", "?")))
    for path, precedent in precedents:
        faults += precedent_faults(precedent, "%s:%s" % (os.path.basename(path),
                                                         precedent.get("name", "?")))
    if args.command == "validate" or faults:
        for fault in faults:
            out.write(fault + "\n")
        out.write("%d brokers, %d modes, %d producers, %d precedents, %d faults\n" % (
            len(brokers), sum(len(b.get("modes") or []) for _, b in brokers),
            sum(len(b.get("producers") or []) for _, b in brokers), len(precedents),
            len(faults)))
        return 1 if faults else 0
    if args.command in ("table", "producers"):
        out.write((table if args.command == "table" else producer_table)(brokers) + "\n")
        return 0
    lines, failures = check(brokers, get, precedents)
    out.write("\n".join(lines) + "\n%d quotes, %d not found or not fetched\n" % (
        len(lines), failures))
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
