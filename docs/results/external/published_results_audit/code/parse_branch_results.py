"""Parse OMB result JSON files found on NON-default branches (branch_scan).

Keeps the printed aggregated end-to-end fields exactly as printed, the per-
window endToEndLatency50pct array (to detect the pre-August-2019 unit bug,
where aggregated end-to-end values were written in microseconds while the
per-window arrays were in milliseconds; fixed by OMB PR #150), and the date of
the branch-head commit that contains the file.
Writes gh/branch_results_parsed.tsv.
"""
import json
import os
import re
import statistics
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
FIELDS = ["50pct", "75pct", "95pct", "99pct", "999pct", "9999pct", "Max", "Avg"]


def printed(raw, key):
    m = re.search(r'"aggregatedEndToEndLatency%s"\s*:\s*(-?[0-9][0-9.eE+-]*|null)' % key, raw)
    return m.group(1) if m else ""


def main():
    out = []
    lines = open(os.path.join("gh", "branch_scan", "hits.tsv"), encoding="utf-8").read().splitlines()[1:]
    for line in lines:
        repo, branch, path, kind = line.split("\t")[:4]
        if kind != "json":
            continue
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", repo + "__" + branch + "__" + path)[:220]
        raw = open(os.path.join("gh", "branch_scan", "files", safe), encoding="utf-8").read()
        try:
            j = json.loads(raw)
        except Exception:  # noqa: BLE001
            j = {}
        win = j.get("endToEndLatency50pct") if isinstance(j, dict) else None
        win_med = statistics.median([x for x in win if isinstance(x, (int, float))]) if isinstance(win, list) and win else ""
        vals = {f: printed(raw, f) for f in FIELDS}
        p50 = vals["50pct"]
        unit_flag = ""
        try:
            if p50 and win_med not in ("", 0) and float(p50) / float(win_med) > 200:
                unit_flag = "AGGREGATED-IN-MICROSECONDS?"
        except Exception:  # noqa: BLE001
            pass
        out.append([repo, branch, path, j.get("workload", "") if isinstance(j, dict) else "", j.get("driver", "") if isinstance(j, dict) else "",
                    str(win_med)] + [vals[f] for f in FIELDS] + [unit_flag])
    with open(os.path.join("gh", "branch_results_parsed.tsv"), "w", encoding="utf-8") as f:
        f.write("\t".join(["repo", "branch", "path", "workload", "driver", "window_p50_median"] + FIELDS + ["unit_flag"]) + "\n")
        for r in out:
            f.write("\t".join(r) + "\n")
    print("parsed", len(out))


if __name__ == "__main__":
    main()
