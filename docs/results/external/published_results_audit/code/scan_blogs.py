"""Scan every blog post URL of the registered vendor blogs for OMB mentions.

For each URL list (one per blog), fetch the page (3 concurrent requests per
site), strip scripts/styles/tags to text, and count:
  om   = case-insensitive "openmessaging"
  omb  = case-sensitive word "OMB"
  e2e  = case-insensitive "end-to-end" or "e2e"
Pages with om>0 or omb>0 are saved to pages/<site>/<n>.html for verification.
Output: scan_<site>.tsv with url, http status, om, omb, e2e, bytes.
"""
import concurrent.futures as cf
import html
import os
import re
import sys
import time
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
RE_OM = re.compile(r"openmessaging", re.I)
RE_OMB = re.compile(r"\bOMB\b")
RE_E2E = re.compile(r"end-to-end|\be2e\b", re.I)


def text_of(raw):
    raw = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return html.unescape(raw)


def fetch(url):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < 2:
                time.sleep(10 * (attempt + 1))
                continue
            return e.code, ""
        except Exception as e:  # noqa: BLE001
            if attempt < 2:
                time.sleep(5)
                continue
            return "ERR:" + type(e).__name__, ""
    return "ERR", ""


def scan(site, urls_file):
    urls = [u.strip() for u in open(urls_file, encoding="utf-8") if u.strip()]
    os.makedirs(os.path.join("pages", site), exist_ok=True)
    out = open("scan_%s.tsv" % site, "w", encoding="utf-8")
    out.write("idx\turl\tstatus\tom\tomb\te2e\tbytes\n")

    def work(item):
        i, u = item
        st, raw = fetch(u)
        t = text_of(raw) if raw else ""
        om, omb, e2e = len(RE_OM.findall(raw)), len(RE_OMB.findall(t)), len(RE_E2E.findall(t))
        if om or omb:
            with open(os.path.join("pages", site, "%04d.html" % i), "w", encoding="utf-8") as f:
                f.write("<!-- %s -->\n" % u)
                f.write(raw)
        time.sleep(0.3)
        return i, u, st, om, omb, e2e, len(raw)

    with cf.ThreadPoolExecutor(max_workers=3) as ex:
        for row in ex.map(work, list(enumerate(urls))):
            out.write("\t".join(str(x) for x in row) + "\n")
            out.flush()
    out.close()
    print("done", site, len(urls), flush=True)


if __name__ == "__main__":
    jobs = [a.split("=", 1) for a in sys.argv[1:]]
    with cf.ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        list(ex.map(lambda j: scan(j[0], j[1]), jobs))
