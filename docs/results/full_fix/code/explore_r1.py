"""Exploratory, after the fact (13 October 2026): in R1's runs of 3 October, the latency to the
kernel's receive time against the latency to the consumer's own timestamp. Per message, from the
producer's send:

  D_app = t_consume - t_send   (what a benchmark reports, timed from the publish call)
  D_k   = t_kernel  - t_send   (to the moment the packet carrying the message's id arrived)
  W     = t_consume - t_kernel (the wake-up, the wait for a core and the client's own work)

Grouped by broker, load and consumer priority. It uses recv_wait.py's own functions unchanged,
reads the R1 runs the integrity rule passed, and writes r1_kernel_vs_app.csv beside this folder.
This reading prompted the block F1 (freezes/39-experiment-plan); it is not part of F1's judging,
which scripts/full_fix.py does.

    python docs/results/full_fix/code/explore_r1.py
"""
import csv
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import recv_wait as rw  # noqa: E402

FOLDERS = [os.path.join(REPO, "runs", "azure", "collected", "matched", name, "runs")
           for name in ("r1", "r1_more")]
BROKER, RECEIVER = "10.1.1.21", "10.1.1.11"


def pct(values, q):
    v = sorted(values)
    return v[min(len(v) - 1, int(q * len(v)))]


rows = []
for run_dir, named, verdict in rw.r1_runs(FOLDERS):
    if verdict != rw.PASSING:
        continue
    row = rw.read_json(os.path.join(run_dir, "queue_row.json"))
    p = row.get("params") or {}
    msgs = rw.messages(run_dir)
    times = rw.kernel_times(os.path.join(run_dir, "receiver_full.pcap"), BROKER, RECEIVER)
    app, k, w = [], [], []
    for eid, send, recv in msgs:
        if eid not in times:
            continue
        app.append((recv - send) / 1e3)
        k.append((times[eid] - send) / 1e3)
        w.append((recv - times[eid]) / 1e3)
    out = {"run": os.path.basename(run_dir), "backend": p.get("backend"),
           "load": p.get("load_pct"), "rt": bool(p.get("consumer_priority")), "n": len(k)}
    for name, vals in (("app", app), ("k", k), ("w", w)):
        out[name + "_med"] = statistics.median(vals)
        out[name + "_mean"] = statistics.fmean(vals)
        out[name + "_p90"] = pct(vals, 0.90)
        out[name + "_p99"] = pct(vals, 0.99)
        out[name + "_min"] = min(vals)
    rows.append(out)
    print("%-44s n=%5d  D_app med %7.0f mean %7.0f p99 %8.0f | D_k med %7.0f mean %7.0f p99 %8.0f min %6.0f"
          % (out["run"], out["n"], out["app_med"], out["app_mean"], out["app_p99"],
             out["k_med"], out["k_mean"], out["k_p99"], out["k_min"]), flush=True)

with open(os.path.join(os.path.dirname(HERE), "r1_kernel_vs_app.csv"), "w", newline="",
          encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

print("\nsetup medians over runs (microseconds)")
groups = {}
for r in rows:
    groups.setdefault((r["backend"], r["load"], r["rt"]), []).append(r)
for key in sorted(groups):
    g = groups[key]

    def m(f):
        return statistics.median(x[f] for x in g)
    print("%-6s load %3s %-6s runs %2d | D_app med %6.0f mean %6.0f p90 %6.0f p99 %7.0f | "
          "D_k med %6.0f mean %6.0f p90 %6.0f p99 %7.0f | W mean %6.0f"
          % (key[0], key[1], "rt" if key[2] else "normal", len(g), m("app_med"), m("app_mean"),
             m("app_p90"), m("app_p99"), m("k_med"), m("k_mean"), m("k_p90"), m("k_p99"),
             m("w_mean")))
