"""Parse OMB result JSON files found in fork repositories.

For each JSON hit in gh/fork_scan/hits_files.tsv: re-read the saved raw file,
extract the printed aggregated end-to-end fields exactly as they appear in the
text (regex on the raw text, so the printed form is kept, e.g. "1.0"), plus
workload and driver names, and the commit that first added the file.
Writes gh/results_parsed.tsv.
"""
import json
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
CLONE = {"snxmlx/openmessaging-benchmark": "a", "Camjo-AB/degree-benchmark": "b",
         "confluentinc/openmessaging-benchmark": "c", "KaimingWan/openmessaging-benchmark": "k",
         "duyvu1109/omb": "d", "seolzero/benchmark-for-DT": "s"}
FIELDS = ["aggregatedEndToEndLatencyAvg", "aggregatedEndToEndLatency50pct", "aggregatedEndToEndLatency75pct",
          "aggregatedEndToEndLatency95pct", "aggregatedEndToEndLatency99pct", "aggregatedEndToEndLatency999pct",
          "aggregatedEndToEndLatency9999pct", "aggregatedEndToEndLatencyMax"]


def printed(raw, key):
    m = re.search(r'"%s"\s*:\s*(-?[0-9][0-9.eE+-]*|null|"[^"]*")' % key, raw)
    return m.group(1) if m else ""


def main():
    rows = []
    for line in open("gh/fork_scan/hits_files.tsv", encoding="utf-8").read().splitlines()[1:]:
        repo, path, kind = line.split("\t")[:3]
        if kind != "json":
            continue
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", repo + "__" + path)[:200]
        raw = open(os.path.join("gh", "fork_scan", "files", safe), encoding="utf-8").read()
        try:
            j = json.loads(raw)
            ok = "yes"
        except Exception:  # noqa: BLE001
            j, ok = {}, "no"
        wl = j.get("workload", "") if isinstance(j, dict) else ""
        drv = j.get("driver", "") if isinstance(j, dict) else ""
        vals = {f: printed(raw, f) for f in FIELDS}
        has_window = "endToEndLatency50pct" in raw
        d = CLONE[repo]
        added = subprocess.run(["git", "-C", os.path.join("clones", d), "log", "--diff-filter=A", "--follow",
                                "--format=%cI %h", "--", path], capture_output=True, text=True).stdout.strip().splitlines()
        added = added[-1] if added else ""
        branch = subprocess.run(["git", "-C", os.path.join("clones", d), "rev-parse", "--abbrev-ref", "HEAD"],
                                capture_output=True, text=True).stdout.strip()
        rows.append([repo, branch, path, ok, wl, drv, added] + [vals[f] for f in FIELDS] + [str(has_window)])
    with open("gh/results_parsed.tsv", "w", encoding="utf-8") as f:
        f.write("\t".join(["repo", "branch", "path", "json_ok", "workload", "driver", "added"] + FIELDS + ["has_window_arrays"]) + "\n")
        for r in rows:
            f.write("\t".join(r) + "\n")
    print("parsed", len(rows))


if __name__ == "__main__":
    main()
