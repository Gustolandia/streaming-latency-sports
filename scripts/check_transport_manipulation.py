"""Did co-location actually shorten the true transport? If not, nothing else in E-A8 follows."""
import glob, json, statistics as st, sys

arms = {}
for pair in sys.argv[1:]:
    name, ts = pair.split("=")
    arms[name] = ts

print("%14s %7s %5s %11s %11s" % ("arm", "backend", "runs", "median p50", "median p99"))
res = {}
for arm, ts in arms.items():
    for b in ("kafka", "redis"):
        p50, p99 = [], []
        for f in glob.glob("runs/concurrency_%s_%s_*/tti_summary.json" % (ts, b)):
            try:
                d = json.load(open(f))
            except Exception:
                continue
            t = d.get("transport_ms") or {}
            if "p50" in t:
                p50.append(t["p50"])
            if "p99" in t:
                p99.append(t["p99"])
        if p50:
            res[(arm, b)] = st.median(p50)
            print("%14s %7s %5d %11.4f %11.4f"
                  % (arm, b, len(p50), st.median(p50), st.median(p99)))

print()
names = list(arms)
if len(names) >= 2:
    a, c = names[0], names[1]
    for b in ("kafka", "redis"):
        x, y = res.get((a, b)), res.get((c, b))
        if x and y:
            print("  %s: T_true %.4f -> %.4f ms   (%.2fx shorter in %s)"
                  % (b, x, y, x / y, c))
