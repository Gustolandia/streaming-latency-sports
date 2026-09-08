#!/usr/bin/env python3
"""
fetch_vocabulary_corpus.py
Build a local corpus of papers from the target journal and its neighbours, so the
manuscript's vocabulary can be checked against how the field actually writes.

The corpus is for READING STATISTICS OFF, not for redistribution: the PDFs land in a
gitignored directory and only the derived term table (scripts/build_vocabulary_table.py)
is committed. Sources are arXiv's public API, which carries a `jr:` (journal-ref) field, so
"papers that appeared in IEEE Transactions on Computers" is a query rather than a guess.

Queries (each capped) --
  journal-ref: Transactions on Computers; Transactions on Parallel and Distributed Systems;
               Transactions on Cloud Computing; ICPE; SIGMETRICS; Middleware; EuroSys; SoCC;
               Performance Evaluation; TOMPECS
  topic (cs.PF / cs.DC / cs.OS): latency benchmark; timestamp; clock synchronization;
               scheduling latency; message broker / Kafka; tail latency; measurement bias

arXiv asks for a 3-second gap between requests; this script honours it, so a full fetch is
about ten minutes. Re-runs skip PDFs already present.

CLI:
    python scripts/fetch_vocabulary_corpus.py [--out docs/reference_corpus] [--per-query 40]
"""
import argparse
import csv
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

API = "http://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom"}
GAP = 3.0  # seconds, arXiv's requested politeness interval

JOURNAL_QUERIES = {
    "tc": 'jr:"Transactions on Computers"',
    "tpds": 'jr:"Transactions on Parallel and Distributed Systems"',
    "tcc": 'jr:"Transactions on Cloud Computing"',
    "icpe": 'jr:ICPE',
    "sigmetrics": 'jr:SIGMETRICS',
    "middleware": 'jr:Middleware',
    "eurosys": 'jr:EuroSys',
    "socc": 'jr:SoCC',
    "peva": 'jr:"Performance Evaluation"',
    "tompecs": 'jr:TOMPECS',
}

#: arXiv's `jr:` field is sparse -- the first fetch matched 0 papers on it -- but authors
#: write the venue into the COMMENTS field ("Accepted to IEEE Transactions on Computers"),
#: which `co:` searches. This is where the same-journal papers actually come from.
COMMENT_QUERIES = {
    "co_tc": 'co:"Transactions on Computers"',
    "co_tpds": 'co:"Transactions on Parallel and Distributed"',
    "co_tcc": 'co:"Transactions on Cloud Computing"',
    "co_tocs": 'co:"Transactions on Computer Systems"',
    "co_tompecs": 'co:TOMPECS',
    "co_icpe": 'co:ICPE',
    "co_sigmetrics": 'co:SIGMETRICS',
    "co_middleware": 'co:Middleware AND (cat:cs.DC OR cat:cs.PF)',
    "co_eurosys": 'co:EuroSys',
    "co_socc": 'co:SoCC',
    "co_atc": 'co:"USENIX ATC"',
    "co_osdi": 'co:OSDI',
    "co_nsdi": 'co:NSDI',
}

#: OpenAlex indexes the journal itself and hands back an open-access PDF where one exists,
#: so "every open-access paper IEEE Transactions on Computers has published" is one query.
OPENALEX = "https://api.openalex.org/works"
OPENALEX_VENUES = {
    "oa_tc": "IEEE Transactions on Computers",
    "oa_tpds": "IEEE Transactions on Parallel and Distributed Systems",
    "oa_tcc": "IEEE Transactions on Cloud Computing",
    "oa_tocs": "ACM Transactions on Computer Systems",
    "oa_tompecs": "ACM Transactions on Modeling and Performance Evaluation of Computing Systems",
    "oa_peva": "Performance Evaluation",
}

TOPIC_QUERIES = {
    "latency_benchmark": '(cat:cs.PF OR cat:cs.DC) AND all:"latency benchmark"',
    "timestamp": '(cat:cs.PF OR cat:cs.DC OR cat:cs.OS) AND all:timestamp AND all:latency',
    "clock_sync": '(cat:cs.DC OR cat:cs.NI) AND all:"clock synchronization"',
    "sched_latency": '(cat:cs.OS OR cat:cs.PF) AND all:"scheduling latency"',
    "broker": '(cat:cs.DC OR cat:cs.PF) AND (all:Kafka OR all:"message broker")',
    "tail_latency": '(cat:cs.PF OR cat:cs.DC) AND all:"tail latency"',
    "measurement_bias": '(cat:cs.PF) AND all:measurement AND all:benchmark AND all:bias',
}


def query(q, max_results):
    url = "%s?%s" % (API, urllib.parse.urlencode(
        {"search_query": q, "start": 0, "max_results": max_results,
         "sortBy": "relevance", "sortOrder": "descending"}))
    with urllib.request.urlopen(url, timeout=60) as r:
        root = ET.fromstring(r.read())
    out = []
    for e in root.findall("a:entry", NS):
        arxiv_id = e.findtext("a:id", "", NS).rsplit("/", 1)[-1]
        title = " ".join((e.findtext("a:title", "", NS) or "").split())
        jr = " ".join((e.findtext("{http://arxiv.org/schemas/atom}journal_ref") or "").split())
        cats = ",".join(c.get("term", "") for c in e.findall("a:category", NS))
        year = (e.findtext("a:published", "", NS) or "")[:4]
        pdf = ""
        for l in e.findall("a:link", NS):
            if l.get("title") == "pdf":
                pdf = l.get("href", "")
        out.append({"arxiv_id": arxiv_id, "title": title, "journal_ref": jr,
                    "categories": cats, "year": year, "pdf": pdf})
    return out


def openalex(venue, per_page):
    """Open-access works whose primary venue is `venue`, newest first, with an OA PDF URL.

    `mailto` puts the request in OpenAlex's polite pool. No key is needed. The filter is on
    the source's display name because OpenAlex source ids differ across mirrors of a journal.
    """
    import json
    url = "%s?%s" % (OPENALEX, urllib.parse.urlencode({
        "filter": "primary_location.source.display_name.search:%s,is_oa:true,type:article" % venue,
        "sort": "publication_date:desc", "per-page": per_page,
        "select": "id,doi,title,publication_year,primary_location,open_access",
        "mailto": "pedrorig@tcd.ie"}))
    with urllib.request.urlopen(url, timeout=60) as r:
        data = json.load(r)
    out = []
    for w in data.get("results", []):
        src = ((w.get("primary_location") or {}).get("source") or {}).get("display_name", "")
        if venue.split()[-1].lower() not in src.lower():
            continue   # "search" is fuzzy; keep only the journal asked for
        pdf = (w.get("open_access") or {}).get("oa_url") or ""
        if not pdf:
            continue
        out.append({"arxiv_id": (w.get("id") or "").rsplit("/", 1)[-1],
                    "title": " ".join((w.get("title") or "").split()),
                    "journal_ref": src, "categories": "openalex",
                    "year": str(w.get("publication_year") or ""), "pdf": pdf})
    return out


def fetch_pdf(url, dest):
    if dest.exists() and dest.stat().st_size > 10_000:
        return "cached"
    req = urllib.request.Request(url, headers={"User-Agent": "vocabulary-corpus/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    # An open-access URL is sometimes a landing page rather than the file. A PDF starts
    # with its own signature; anything else is not a paper and is not kept.
    if not data.startswith(b"%PDF"):
        return "not-a-pdf"
    dest.write_bytes(data)
    return "fetched"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/reference_corpus")
    ap.add_argument("--per-query", type=int, default=40)
    ap.add_argument("--no-download", action="store_true", help="manifest only")
    args = ap.parse_args(argv)

    out = Path(args.out)
    (out / "pdf").mkdir(parents=True, exist_ok=True)
    seen, rows = {}, []
    stages = (("journal", JOURNAL_QUERIES), ("comment", COMMENT_QUERIES),
              ("topic", TOPIC_QUERIES), ("openalex", OPENALEX_VENUES))
    for group, qs in stages:
        for key, q in qs.items():
            try:
                if group == "openalex":
                    hits = openalex(q, min(args.per_query * 4, 200))
                else:
                    hits = query(q, args.per_query)
            except Exception as e:  # pragma: no cover - network
                print("query %s failed: %s" % (key, e))
                hits = []
            new = 0
            for h in hits:
                if h["arxiv_id"] in seen:
                    seen[h["arxiv_id"]]["matched"] += "|" + key
                    continue
                h["matched"] = key
                h["group"] = group
                seen[h["arxiv_id"]] = h
                rows.append(h)
                new += 1
            print("%-18s %3d hits, %3d new" % (key, len(hits), new))
            time.sleep(GAP)

    manifest = out / "manifest.csv"
    with open(manifest, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["arxiv_id", "title", "journal_ref", "categories",
                                           "year", "group", "matched", "pdf"])
        w.writeheader()
        w.writerows(rows)
    print("manifest: %s (%d papers)" % (manifest, len(rows)))

    if args.no_download:
        return 0
    got = 0
    for i, h in enumerate(rows, 1):
        if not h["pdf"]:
            continue
        safe = re.sub(r"[^A-Za-z0-9.]+", "_", h["arxiv_id"])
        dest = out / "pdf" / ("%s.pdf" % safe)
        try:
            status = fetch_pdf(h["pdf"], dest)
            got += 1
        except Exception as e:  # pragma: no cover - network
            status = "FAILED %s" % e
        print("[%3d/%d] %-14s %s" % (i, len(rows), h["arxiv_id"], status))
        if status == "fetched":
            time.sleep(GAP)
    print("pdfs present: %d" % got)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
