"""Build configurations.csv from the coded reports, verifying every quote.

Each report in rows_*.py is a dict with report-level fields and a list of
configurations. For text sources, every quote (whitespace-collapsed) must be
a substring of the saved source text, and every number coded in e2e_p50_ms /
e2e_p99_ms must appear inside its quote. Image sources are checked by eye
(twice) and flagged in notes; JSON sources are checked against the file.
"""
import csv
import glob
import importlib.util
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.dirname(HERE)

COLS = ["row_id", "registered_source", "report_url", "report_date", "retrieved", "tool", "broker",
        "configuration", "e2e_p50_ms", "e2e_p99_ms", "other_e2e_percentiles", "quote",
        "included", "reason", "notes"]


def norm(s):
    s = s.replace("‑", "-").replace("–", "-").replace("—", "-")
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace(" ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def load_reports():
    reps = []
    for path in sorted(glob.glob(os.path.join(HERE, "rows_*.py"))):
        spec = importlib.util.spec_from_file_location(os.path.basename(path)[:-3], path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        reps.extend(mod.REPORTS)
    return reps


def numbers(v):
    return [n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", v or "")]


def main():
    reps = load_reports()
    rows, problems, n = [], [], 0
    cache = {}
    for rep in reps:
        src = rep.get("src")
        kind = rep.get("src_kind", "text")
        text = None
        if src and kind in ("text", "json"):
            p = os.path.join(HERE, src)
            if p not in cache:
                cache[p] = norm(open(p, encoding="utf-8", errors="replace").read())
            text = cache[p]
        confs = rep.get("configs") or [dict()]
        for c in confs:
            n += 1
            quote = c.get("quote", "")
            if quote and text is not None and c.get("check", True):
                if norm(quote) not in text:
                    problems.append("QUOTE NOT FOUND [%s | %s]: %s" % (rep["id"], c.get("configuration", ""), quote[:120]))
            for col in ("e2e_p50_ms", "e2e_p99_ms"):
                for num in numbers(c.get(col, "")):
                    if c.get("check", True) and quote and num not in norm(quote).replace(",", ""):
                        if not c.get("converted"):
                            problems.append("NUMBER %s (%s) NOT IN QUOTE [%s | %s]" % (num, col, rep["id"], c.get("configuration", "")))
            inc = c.get("included", rep.get("included", "no"))
            rows.append({
                "row_id": "R%04d" % n,
                "registered_source": rep.get("source", ""),
                "report_url": rep["url"],
                "report_date": c.get("date") or rep.get("date", ""),
                "retrieved": rep.get("retrieved", "2026-09-28"),
                "tool": rep.get("tool", ""),
                "broker": c.get("broker", rep.get("broker", "")),
                "configuration": c.get("configuration", ""),
                "e2e_p50_ms": c.get("e2e_p50_ms", ""),
                "e2e_p99_ms": c.get("e2e_p99_ms", ""),
                "other_e2e_percentiles": c.get("other", ""),
                "quote": quote,
                "included": inc,
                "reason": c.get("reason", rep.get("reason", "")),
                "notes": "; ".join(x for x in (rep.get("notes", ""), c.get("notes", "")) if x),
            })
    with open(os.path.join(OUT, "configurations.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    print("reports", len(reps), "rows", len(rows))
    print("problems", len(problems))
    for p in problems:
        print("  ", p)


if __name__ == "__main__":
    main()
