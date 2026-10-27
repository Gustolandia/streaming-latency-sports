#!/usr/bin/env python3
"""
broker_audit.py -- the broker audit's records, the verdicts they lead to, and a fetch-back of every
quote they rest on.

The protocol is data/broker_audit/PROTOCOL.md, registered before any record was coded. Each record
says, for one broker and one of its consumer interfaces, which times the broker keeps for a message
and which it hands the consumer, with a quote from a pinned source for every answer. The verdicts
are not stored anywhere. They are computed here, from the answers, by the rules the protocol
registered, so a reader who disagrees with a verdict can find the answer it came from.

CLI:
    python scripts/broker_audit.py validate [FILE ...]   # the form of every record; offline
    python scripts/broker_audit.py table [FILE ...]      # the verdicts, as a Markdown table
    python scripts/broker_audit.py check [FILE ...]      # fetch every URL and find every quote

With no FILE, it reads data/broker_audit/batch_*.json. `check` needs the network and is not part of
the test suite, for the reason scripts/check_upstream_lines.py gives: a check whose answer depends
on what a stranger changed this morning must not turn the build red. Its exit status is 1 if any
quote is missing or any fetch failed.
"""
import argparse
import glob
import html
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORDS = os.path.join(ROOT, "data", "broker_audit", "batch_*.json")
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
STAMPED = ("always", "by configuration")
WAITING = ("standing", "credit or several")
#: Branch names that move. A URL into a repository must name a tag or a commit instead.
MOVING = ("main", "master", "head", "trunk", "develop", "dev", "latest", "gh-pages")
QUOTE_MOST = 300


def load(paths=None):
    """Every broker of every batch, in file order, each with the file it came from."""
    paths = sorted(glob.glob(RECORDS)) if not paths else paths
    out = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            batch = json.load(fh)
        for broker in batch.get("brokers", []):
            out.append((path, broker))
    return out


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


def broker_faults(broker, where):
    """What is wrong with one broker's record."""
    faults = []
    for key in ("broker", "version"):
        if not isinstance(broker.get(key), str) or not broker[key].strip():
            faults.append("%s: %s is missing" % (where, key))
    if broker.get("group") not in ("A", "B"):
        faults.append("%s: group is A or B" % where)
    if not broker.get("version_evidence"):
        faults.append("%s: the version has no evidence" % where)
    faults += evidence_faults(broker.get("version_evidence") or [], where + ".version_evidence")
    modes = broker.get("modes") or []
    if not modes:
        faults.append("%s: no modes" % where)
    for mode in modes:
        faults += mode_faults(mode, "%s/%s" % (where, mode.get("mode", "?")))
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
    """The text at a URL. `opener` is injected by the tests."""
    opener = opener or urllib.request.urlopen
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with opener(request, timeout=60) as response:
        return response.read().decode("utf-8", errors="replace")


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


def every_quote(brokers):
    """(where, url, quote) for every evidence item of every record."""
    for path, broker in brokers:
        name = os.path.basename(path) + ":" + broker.get("broker", "?")
        for item in broker.get("version_evidence") or []:
            yield name + ".version", item["url"], item["quote"]
        for mode in broker.get("modes") or []:
            for q in QUESTIONS:
                for item in (mode.get(q) or {}).get("evidence") or []:
                    yield "%s/%s.%s" % (name, mode.get("mode", "?"), q), item["url"], item["quote"]


def check(brokers, get=fetch):
    """Fetch every URL once and look for every quote in it. Returns (lines, failures)."""
    pages, lines, failures = {}, [], 0
    for where, url, quote in every_quote(brokers):
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
    parser.add_argument("command", choices=("validate", "table", "check"))
    parser.add_argument("files", nargs="*")
    args = parser.parse_args(argv)
    brokers = load(args.files)
    faults = []
    for path, broker in brokers:
        faults += broker_faults(broker, "%s:%s" % (os.path.basename(path),
                                                   broker.get("broker", "?")))
    if args.command == "validate" or faults:
        for fault in faults:
            out.write(fault + "\n")
        out.write("%d brokers, %d modes, %d faults\n" % (
            len(brokers), sum(len(b.get("modes") or []) for _, b in brokers), len(faults)))
        return 1 if faults else 0
    if args.command == "table":
        out.write(table(brokers) + "\n")
        return 0
    lines, failures = check(brokers, get)
    out.write("\n".join(lines) + "\n%d quotes, %d not found or not fetched\n" % (
        len(lines), failures))
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
