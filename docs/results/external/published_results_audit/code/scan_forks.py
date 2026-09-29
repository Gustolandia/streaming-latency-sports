"""Scan openmessaging/benchmark, its detached copies, and every fork network.

For every repository:
  * issues + issue comments (if issues are enabled): flag texts with an
    end-to-end term (e2e / end-to-end / endToEnd) on a line with a digit;
  * default-branch tree: flag files that are new or changed relative to the
    upstream trees (blob SHA not seen upstream) with a text/result extension,
    fetch them, and flag
      - JSON with an endToEndLatency / aggregatedEndToEndLatency key,
      - text lines with an end-to-end term and a digit.
Outputs gh/fork_scan/{repos.json, hits_issues.tsv, hits_files.tsv, files/...}.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

OUT = os.path.join("gh", "fork_scan")
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
        if "rate limit" in p.stderr.lower() or "secondary" in p.stderr.lower():
            time.sleep(60)
            continue
        if "404" in p.stderr or "409" in p.stderr or "Not Found" in p.stderr:
            return None
        time.sleep(3)
    return None


def network(seed):
    out, queue, seen = [], [seed], set()
    while queue:
        r = queue.pop(0)
        for f in gh("repos/%s/forks?per_page=100" % r, paginate=True) or []:
            if f["full_name"] in seen:
                continue
            seen.add(f["full_name"])
            out.append(f)
            if f["forks_count"] > 0:
                queue.append(f["full_name"])
    return out


def tree(full, branch):
    t = gh("repos/%s/git/trees/%s?recursive=1" % (full, branch))
    if not t:
        return [], False
    return [x for x in t.get("tree", []) if x["type"] == "blob"], t.get("truncated", False)


def main(seeds):
    upstream_blobs = set()
    repos = {}
    for s in seeds:
        meta = gh("repos/%s" % s)
        if meta:
            repos[s] = {"full_name": s, "seed": s, "parent": "-", "fork": meta["fork"],
                        "default_branch": meta["default_branch"], "has_issues": meta["has_issues"],
                        "pushed_at": meta["pushed_at"], "created_at": meta["created_at"]}
        for f in network(s):
            repos.setdefault(f["full_name"], {
                "full_name": f["full_name"], "seed": s, "parent": (f.get("parent") or {}).get("full_name", "?"),
                "fork": True, "default_branch": f["default_branch"], "has_issues": f["has_issues"],
                "pushed_at": f["pushed_at"], "created_at": f["created_at"]})
    json.dump(list(repos.values()), open(os.path.join(OUT, "repos.json"), "w", encoding="utf-8"), indent=0)
    print("repos to scan", len(repos), flush=True)

    base, _ = tree("openmessaging/benchmark", "master")
    upstream_blobs.update(x["sha"] for x in base)

    hi = open(os.path.join(OUT, "hits_issues.tsv"), "w", encoding="utf-8")
    hf = open(os.path.join(OUT, "hits_files.tsv"), "w", encoding="utf-8")
    hf.write("repo\tpath\tkind\tdetail\n")
    hi.write("repo\turl\tcreated\tline\n")
    log = open(os.path.join(OUT, "scan_log.tsv"), "w", encoding="utf-8")
    log.write("repo\tseed\tfork\tissues_enabled\tn_issues\tn_comments\tn_blobs\ttruncated\tn_candidates\n")
    # seeds first so their blobs become baselines for their own forks
    order = [r for r in repos if r in seeds] + [r for r in repos if r not in seeds]
    for full in order:
        r = repos[full]
        n_iss = n_com = 0
        if r["has_issues"]:
            iss = gh("repos/%s/issues?state=all&per_page=100" % full, paginate=True) or []
            com = (gh("repos/%s/issues/comments?per_page=100" % full, paginate=True) or []) if iss else []
            n_iss, n_com = len(iss), len(com)
            for x in iss + com:
                body = (x.get("title") or "") + "\n" + (x.get("body") or "")
                for line in body.splitlines():
                    if E2E.search(line) and DIGIT.search(line):
                        hi.write("%s\t%s\t%s\t%s\n" % (full, x["html_url"], x["created_at"][:10], line.strip()[:300].replace("\t", " ")))
            hi.flush()
        blobs, trunc = tree(full, r["default_branch"])
        cands = [b for b in blobs if b["sha"] not in upstream_blobs and EXT.search(b["path"]) and not SKIP.search(b["path"])]
        for b in cands:
            url = "https://raw.githubusercontent.com/%s/%s/%s" % (
                full, urllib.parse.quote(r["default_branch"]), urllib.parse.quote(b["path"]))
            raw = None
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(url, timeout=60) as resp:
                        raw = resp.read().decode("utf-8", "replace")
                    break
                except Exception:  # noqa: BLE001
                    time.sleep(3)
            if raw is None:
                hf.write("%s\t%s\tFETCH-FAILED\t%s\n" % (full, b["path"], url))
                continue
            keyhit = re.findall(r'"(aggregatedEndToEndLatency50pct|endToEndLatency50pct)"\s*:\s*([^,\]\}]+)', raw)
            texthits = [l.strip() for l in raw.splitlines() if E2E.search(l) and DIGIT.search(l)] if not keyhit else []
            if keyhit or texthits:
                safe = re.sub(r"[^A-Za-z0-9._-]", "_", full + "__" + b["path"])[:200]
                open(os.path.join(OUT, "files", safe), "w", encoding="utf-8").write(raw)
                if keyhit:
                    hf.write("%s\t%s\tjson\t%s\n" % (full, b["path"], ";".join("%s=%s" % (k, v.strip()[:40]) for k, v in keyhit[:4])))
                else:
                    hf.write("%s\t%s\ttext\t%s\n" % (full, b["path"], " || ".join(t[:160].replace("\t", " ") for t in texthits[:3])))
                hf.flush()
        if full in seeds:
            upstream_blobs.update(x["sha"] for x in blobs)
        log.write("%s\t%s\t%s\t%s\t%d\t%d\t%d\t%s\t%d\n" % (full, r["seed"], r["fork"], r["has_issues"], n_iss, n_com, len(blobs), trunc, len(cands)))
        log.flush()
    print("done", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
