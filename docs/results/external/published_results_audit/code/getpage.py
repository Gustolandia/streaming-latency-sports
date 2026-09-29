"""Fetch a report page, save raw HTML and a table-aware text rendering.

Usage: python getpage.py <id> <url> [pattern]
Writes reports/<id>.html and reports/<id>.txt (one block per line, table cells
separated by ' | '), then prints numbered lines matching the pattern
(default: latency/percentile/OMB terms).
"""
import html
import re
import sys
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def to_text(raw):
    t = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw)
    t = re.sub(r"(?i)</(p|h\d|li|tr|div|table|figcaption|pre|blockquote|section|article)\s*>", "\n", t)
    t = re.sub(r"(?i)<br\s*/?>", "\n", t)
    t = re.sub(r"(?i)</t[dh]>", " | ", t)
    t = re.sub(r"(?s)<[^>]+>", "", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t\xa0​]+", " ", t)
    return "\n".join(l.strip() for l in t.splitlines() if l.strip())


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rid, url = sys.argv[1], sys.argv[2]
    pat = sys.argv[3] if len(sys.argv) > 3 else r"(?i)(latenc|p50|p99|p95|p999|median|percentile|openmessaging|\bOMB\b|end-to-end|\be2e\b)"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read().decode("utf-8", "replace")
        final = r.geturl()
    open("reports/%s.html" % rid, "w", encoding="utf-8").write("<!-- %s -->\n" % final + raw)
    txt = to_text(raw)
    open("reports/%s.txt" % rid, "w", encoding="utf-8").write(txt)
    lines = txt.splitlines()
    print("final url:", final, "| lines:", len(lines))
    for m in re.finditer(r'"(datePublished|dateModified|article:published_time|published_time)"?\s*[:=]?\s*(content=)?"([^"]+)"', raw):
        print("date meta:", m.group(1), m.group(3))
        break
    for i, l in enumerate(lines):
        if re.search(pat, l):
            print(i, ":", l[:500])


if __name__ == "__main__":
    main()
