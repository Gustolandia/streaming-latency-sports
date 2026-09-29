"""Resolve Google /goto?url=... result tokens to their destination URLs.

Reads a JSON list of {t: title, c: cite, h: href} captured from a Google results
page, requests each href from www.google.com WITHOUT following the redirect,
and prints rank, title and the Location header (the destination URL).
Usage: python resolve_goto.py page.json start_rank > page.tsv
"""
import json
import sys
import time
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


opener = urllib.request.build_opener(NoRedirect)
items = json.load(open(sys.argv[1], encoding="utf-8"))
start = int(sys.argv[2]) if len(sys.argv) > 2 else 1
for i, it in enumerate(items):
    href = it["h"]
    url = href if href.startswith("http") else "https://www.google.com" + href
    dest = ""
    if "/goto?" in url or "/url?" in url:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            opener.open(req, timeout=30)
            dest = "NO-REDIRECT"
        except urllib.error.HTTPError as e:
            dest = e.headers.get("Location") or ("HTTP %d" % e.code)
        except Exception as e:  # noqa: BLE001
            dest = "ERROR %s" % e
        time.sleep(0.5)
    else:
        dest = url
    print("%d\t%s\t%s\t%s" % (start + i, it["t"], it["c"], dest))
