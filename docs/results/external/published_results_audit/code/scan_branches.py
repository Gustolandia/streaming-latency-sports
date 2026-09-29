"""Scan NON-default branches of every repository in the OMB fork networks.

Same detection rule as scan_forks.py (result JSON keys; e2e term + digit on a
text line), applied to files on non-default branches whose blob SHA is not
already known from: all branches of openmessaging/benchmark, the repository's
own default branch, or any branch processed earlier. Branch heads whose commit
was already processed are skipped (identical trees).
Outputs gh/branch_scan/{log.tsv,hits.tsv,files/}.
"""
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request

OUT = os.path.join("gh", "branch_scan")
os.makedirs(os.path.join(OUT, "files"), exist_ok=True)
E2E = re.compile(r"(?i)(\be2e\b|end[- ]?to[- ]?end|endtoend)")
DIGIT = re.compile(r"\d")
EXT = re.compile(r"(?i)\.(json|md|markdown|txt|html?|csv|tsv|ipynb|rst|adoc|log|out)$")
SKIP = re.compile(r"(?i)(node_modules/|/target/|\.github/|package(-lock)?\.json$|tsconfig|\.eslintrc)")


def gh(path, paginate=False):
    args = ["gh", "api"] + (["--paginate", "--slurp"] if paginate else []) + [path]
    for attempt in range(4):
        p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
        if p.returncode == 0:
            d = json.loads(p.stdout) if p.stdout.strip() else None
            if paginate and d is not None:
                d = [x for page in d for x in (page if isinstance(page, list) else [page])]
            return d
        if "rate limit" in p.stderr.lower():
            time.sleep(60)
            continue
        if "404" in p.stderr or "409" in p.stderr or "Not Found" in p.stderr:
            return None
        time.sleep(3)
    return None


def blobs(full, ref):
    t = gh("repos/%s/git/trees/%s?recursive=1" % (full, urllib.parse.quote(ref, safe="")))
    if not t:
        return [], False
    return [x for x in t.get("tree", []) if x["type"] == "blob"], t.get("truncated", False)


def main():
    repos = json.load(open(os.path.join("gh", "fork_scan", "repos.json"), encoding="utf-8"))
    known = set()
    seen_commits = set()
    log = open(os.path.join(OUT, "log.tsv"), "w", encoding="utf-8")
    hits = open(os.path.join(OUT, "hits.tsv"), "w", encoding="utf-8")
    log.write("repo\tbranch\tcommit\tstatus\tn_blobs\tn_candidates\n")
    hits.write("repo\tbranch\tpath\tkind\tdetail\n")
    # upstream: all branches first
    order = ["openmessaging/benchmark"] + [r["full_name"] for r in repos if r["full_name"] != "openmessaging/benchmark"]
    default = {r["full_name"]: r["default_branch"] for r in repos}
    default["openmessaging/benchmark"] = "master"
    for full in order:
        brs = gh("repos/%s/branches?per_page=100" % full, paginate=True) or []
        # the repository's default branch blobs are already covered by scan_forks
        d_bl, _ = blobs(full, default.get(full, "master"))
        known.update(b["sha"] for b in d_bl)
        for br in brs:
            name, sha = br["name"], br["commit"]["sha"]
            if name == default.get(full) and full != "openmessaging/benchmark":
                continue
            if sha in seen_commits:
                log.write("%s\t%s\t%s\tsame-commit-seen\t0\t0\n" % (full, name, sha[:7]))
                continue
            seen_commits.add(sha)
            bl, trunc = blobs(full, sha)
            if full == "openmessaging/benchmark":
                known.update(b["sha"] for b in bl)
                log.write("%s\t%s\t%s\tupstream-baseline\t%d\t0\n" % (full, name, sha[:7], len(bl)))
                continue
            cands = [b for b in bl if b["sha"] not in known and EXT.search(b["path"]) and not SKIP.search(b["path"])]
            for b in cands:
                url = "https://raw.githubusercontent.com/%s/%s/%s" % (full, sha, urllib.parse.quote(b["path"]))
                raw = None
                for attempt in range(3):
                    try:
                        with urllib.request.urlopen(url, timeout=60) as resp:
                            raw = resp.read().decode("utf-8", "replace")
                        break
                    except Exception:  # noqa: BLE001
                        time.sleep(3)
                if raw is None:
                    hits.write("%s\t%s\t%s\tFETCH-FAILED\t%s\n" % (full, name, b["path"], url))
                    continue
                keyhit = re.findall(r'"(aggregatedEndToEndLatency50pct|endToEndLatency50pct)"\s*:\s*([^,\]\}]+)', raw)
                texthits = [l.strip() for l in raw.splitlines() if E2E.search(l) and DIGIT.search(l)] if not keyhit else []
                if keyhit or texthits:
                    safe = re.sub(r"[^A-Za-z0-9._-]", "_", full + "__" + name + "__" + b["path"])[:220]
                    open(os.path.join(OUT, "files", safe), "w", encoding="utf-8").write(raw)
                    if keyhit:
                        hits.write("%s\t%s\t%s\tjson\t%s\n" % (full, name, b["path"], ";".join("%s=%s" % (k, v.strip()[:40]) for k, v in keyhit[:2])))
                    else:
                        hits.write("%s\t%s\t%s\ttext\t%s\n" % (full, name, b["path"], " || ".join(t[:160].replace("\t", " ") for t in texthits[:3])))
                    hits.flush()
            known.update(b["sha"] for b in bl)
            log.write("%s\t%s\t%s\tscanned%s\t%d\t%d\n" % (full, name, sha[:7], "-TRUNCATED" if trunc else "", len(bl), len(cands)))
            log.flush()
    print("done", flush=True)


if __name__ == "__main__":
    main()
