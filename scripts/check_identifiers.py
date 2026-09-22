#!/usr/bin/env python3
"""
check_identifiers.py -- ask every identifier this repository states as fact whether it exists.

Why this exists. On 22 September 2026 five of the six commit hashes pinning the tools block were
found not to be commits: not recorded against the wrong repository, but absent from GitHub
entirely. They had been written two days earlier, in the same commit that created the file, and
nothing had read them since -- the install step that would have fetched those commits fetched
nothing, so nothing could contradict them. The real versions were in this repository the whole
time, in data/tools_audit/, mangled in the copying: each wrong hash shares its first 28 to 34
characters with the right one and differs only in the tail.

The lesson is not about that file. An identifier nobody fetches is an identifier nobody checks,
and a plausible one sitting beside careful work inherits the credibility of the work beside it.
So this collects the identifiers the repository asserts and asks their sources:

  tool pins      the commit or version each tool in cloud/azure/tools.sh is run at, against
                 GitHub, and against data/tools_audit/, which is where they should have come from
  bibliography   every DOI in manuscript_references.bib, against Crossref
  arXiv          every arXiv identifier cited, against arxiv.org
  deposits       every Zenodo DOI this repository publishes, against Zenodo

It changes nothing. It reports, and exits 1 if anything it asked about does not exist, so it can
be run in CI or by hand before a deposit.

CLI:
    python3 scripts/check_identifiers.py                 # check everything, network needed
    python3 scripts/check_identifiers.py --list          # what it would check, no network
    python3 scripts/check_identifiers.py --only tools    # one group
"""
import argparse
import json
import os
import re
import sys
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT = "sbl-identifier-check/1.0"
GROUPS = ("tools", "doi", "arxiv", "zenodo")


def read(*parts):
    path = os.path.join(REPO, *parts)
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


# --- what the repository asserts -------------------------------------------------------------

def tool_pins(text=None):
    """(tool, kind, version) for each row of tools.sh's PINNED table."""
    text = read("cloud", "azure", "tools.sh") if text is None else text
    if "PINNED='" not in text:
        return []
    table = text.split("PINNED='", 1)[1].split("'", 1)[0]
    out = []
    for line in table.strip().splitlines():
        bits = line.split("|")
        if len(bits) == 3:
            out.append((bits[0].strip(), bits[1].strip(), bits[2].strip()))
    return out


#: Where each tool's source lives, so a pinned commit can be asked of the right repository. A
#: tool whose pin is a release or a version rather than a commit is checked by the audit record
#: alone, because there is no commit to ask about.
REPOS = {
    "vegeta": "tsenart/vegeta",
    "hey": "rakyll/hey",
    "k6": "grafana/k6",
    "memtier_benchmark": "RedisLabs/memtier_benchmark",
    "rdkafka_performance": "confluentinc/librdkafka",
    "kafka-end-to-end": "apache/kafka",
    "kafka-producer-perf": "apache/kafka",
    "wrk2": "giltene/wrk2",
    "rabbitmq-perftest": "rabbitmq/rabbitmq-perf-test",
    "nats-latency": "nats-io/natscli",
}


def audited_versions(texts=None):
    """Every "version seen" string the T5 audit recorded, as one blob per batch file."""
    if texts is None:
        folder = os.path.join(REPO, "data", "tools_audit")
        texts = []
        if os.path.isdir(folder):
            for name in sorted(os.listdir(folder)):
                if name.endswith(".json"):
                    texts.append(read("data", "tools_audit", name))
    return " ".join(texts)


def dois(text=None):
    text = read("manuscript_references.bib") if text is None else text
    found = re.findall(r"doi\s*=\s*[{\"]([^}\"]+)", text, re.I)
    return sorted({d.strip().replace("https://doi.org/", "") for d in found})


def arxiv_ids(text=None):
    text = read("manuscript_references.bib") if text is None else text
    return sorted(set(re.findall(r"arXiv[: ]\s*(\d{4}\.\d{4,5})", text, re.I)))


def zenodo_ids(texts=None):
    if texts is None:
        texts = [read("README.md"), read("CITATION.cff"), read("docs", "releases.md")]
    found = []
    for text in texts:
        found += re.findall(r"10\.5281/zenodo\.(\d+)", text)
    return sorted(set(found), key=int)


# --- asking their sources --------------------------------------------------------------------

def http_ok(url, fetch=None):
    """Whether a URL answers, with the fetcher injectable so the tests need no network."""
    if fetch is None:                                        # pragma: no cover - needs network
        def fetch(target):
            request = urllib.request.Request(target, headers={"User-Agent": AGENT})
            with urllib.request.urlopen(request, timeout=45) as handle:
                return handle.status
    try:
        return fetch(url) == 200
    except Exception:
        return False


def check(only=None, fetch=None):
    """[(group, what, ok, why)] for every identifier asked about."""
    out = []
    want = set(GROUPS if only is None else [only])

    if "tools" in want:
        audit = audited_versions()
        for tool, _kind, version in tool_pins():
            if re.fullmatch(r"[0-9a-f]{7,40}", version):
                repo = REPOS.get(tool)
                ok = repo is not None and http_ok(
                    "https://api.github.com/repos/%s/commits/%s" % (repo, version), fetch)
                why = "not a commit in %s" % repo if not ok else ""
            else:
                ok, why = True, "not a commit, so only the audit record can say"
            if version not in audit:
                ok = False
                why = (why + "; " if why else "") + "not the version data/tools_audit records"
            out.append(("tools", "%s %s" % (tool, version), ok, why))

    if "doi" in want:
        for doi in dois():
            ok = http_ok("https://api.crossref.org/works/" + urllib.request.quote(doi), fetch)
            out.append(("doi", doi, ok, "" if ok else "resolves to nothing"))

    if "arxiv" in want:
        for ident in arxiv_ids():
            ok = http_ok("https://arxiv.org/abs/" + ident, fetch)
            out.append(("arxiv", ident, ok, "" if ok else "no such preprint"))

    if "zenodo" in want:
        for ident in zenodo_ids():
            ok = http_ok("https://zenodo.org/api/records/" + ident, fetch)
            out.append(("zenodo", ident, ok, "" if ok else "no such record"))

    return out


def listing():
    return [("tools", "%s %s" % (t, v)) for t, _k, v in tool_pins()] \
        + [("doi", d) for d in dois()] \
        + [("arxiv", a) for a in arxiv_ids()] \
        + [("zenodo", z) for z in zenodo_ids()]


def main(argv=None, out=None, fetch=None):
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--list", action="store_true",
                        help="what it would check, without asking anything")
    parser.add_argument("--only", choices=GROUPS, help="one group rather than all of them")
    args = parser.parse_args(argv)

    if args.list:
        for group, what in listing():
            out.write("%-7s %s\n" % (group, what))
        return 0

    found = check(args.only, fetch)
    bad = [row for row in found if not row[2]]
    for group, what, ok, why in found:
        out.write("%-7s %-46s %s\n" % (group, what[:46], "ok" if ok else "** %s **" % why))
    out.write("\n%d asked, %d that do not exist\n" % (len(found), len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":                                   # pragma: no cover - the CLI
    raise SystemExit(main())
