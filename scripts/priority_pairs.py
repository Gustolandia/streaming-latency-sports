"""Every real-time-priority matched pair, from every campaign that ran one.

The manuscript's headline for Mode A's mitigation is a range -- "collapses it 7-80x" -- taken
over eight matched pairs spanning 60 to 95% load. Two of those pairs were shown, in the main
text's Table II and again in the supplement, and the other six were in neither document. The
range was correct and reproduced exactly from the committed artifacts; there was simply no
path from the abstract to it, and the pair that anchors its lower bound is the weakest result
in the series and the one a sceptic would most want to see.

`stat_intervals.priority_cells` reads one of the three files, which is right for the two pairs
Table II reports and wrong for the range. This reads all three, keeps the campaign each pair
came from, and is where the range now comes from.

**Confounded pairs are excluded and counted.** The design assumes real-time priority leaves
utilization alone; `analyze_stamping_priority.py` measures rho in both arms and marks a pair
confounded when they disagree beyond tolerance, because a cell whose manipulation check failed
yields no finding rather than a hedged one. Excluding them silently would let the range be
built from cells the campaign itself refused to report.
"""

import csv
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = os.path.join(REPO, "docs", "results", "model")

#: The campaigns that ran a priority manipulation, in the order the supplement names them.
#: E-A5 is the original; E-A5b widened the load ladder; E-A7 replicated E-A5.
CAMPAIGNS = (
    ("E-A5", "stamping_priority.csv"),
    ("E-A5b", "stamping_priority_ea5b.csv"),
    ("E-A7", "stamping_priority_ea7.csv"),
)


def _load(path):
    full = os.path.join(MODEL, path)
    if not os.path.exists(full):
        return []
    with open(full, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def pairs(campaigns=CAMPAIGNS):
    """Every matched pair, unconfounded first, each tagged with its campaign.

    `factor` is the collapse the manuscript quotes: the ordinary rate over the real-time rate.
    The stored `ratio` column is its reciprocal, which is why this recomputes rather than
    reads it -- two names for one quantity is how a sign gets inverted in a revision.
    """
    out = []
    for name, filename in campaigns:
        for r in _load(filename):
            try:
                base, rt = float(r["inv_base"]), float(r["inv_rt"])
                n_base, n_rt = int(r["n_base"]), int(r["n_rt"])
                rho = float(r["rho_base"])
            except (KeyError, TypeError, ValueError):
                continue
            out.append({
                "campaign": name,
                "level": r.get("level", ""),
                "rho": rho,
                "rho_rt": float(r.get("rho_rt", rho) or rho),
                "rate_base": base,
                "rate_rt": rt,
                "n_base": n_base,
                "n_rt": n_rt,
                "factor": (base / rt) if rt > 0 else float("inf"),
                "disjoint": str(r.get("disjoint")) == "True",
                "confounded": str(r.get("confounded")) == "True",
            })
    out.sort(key=lambda d: d["rho"])
    return out


def usable(campaigns=CAMPAIGNS):
    """The pairs the range is entitled to be built from."""
    return [p for p in pairs(campaigns) if not p["confounded"]]


def summary(campaigns=CAMPAIGNS):
    """The quantities the manuscript quotes."""
    good = usable(campaigns)
    if not good:
        return {"pairs": 0, "confounded": 0, "factor_low": 0.0, "factor_high": 0.0,
                "rho_low": 0.0, "rho_high": 0.0, "level_low": 0, "level_high": 0,
                "all_disjoint": False}
    factors = [p["factor"] for p in good]
    rhos = [p["rho"] for p in good]
    # The load range is the nominal ladder the campaign set, which is what "60 to 95% load"
    # means and what the table's load column shows. Achieved rho lands near but not on it
    # -- 0.6055 at l60 -- and rounding that gives 61, a number nobody chose.
    levels = [int(p["level"].lstrip("l")) for p in good if p["level"].lstrip("l").isdigit()]
    return {
        "pairs": len(good),
        "confounded": sum(1 for p in pairs(campaigns) if p["confounded"]),
        "factor_low": min(factors),
        "factor_high": max(factors),
        "rho_low": min(rhos),
        "rho_high": max(rhos),
        "level_low": min(levels) if levels else 0,
        "level_high": max(levels) if levels else 0,
        "all_disjoint": all(p["disjoint"] for p in good),
    }


def main(argv=None):
    """Print every matched pair and the range they give.

    A function rather than a block under the `__main__` guard: the guard is excluded from
    coverage, and this loop is what shows the eight pairs the abstract's range comes from.
    """
    s = summary()
    print("%-7s %-6s %-8s %-10s %-10s %-8s %s"
          % ("camp", "level", "rho", "ordinary", "real-time", "factor", "disjoint"))
    print("-" * 68)
    for pair in usable():
        print("%-7s %-6s %-8.3f %-10.4f %-10.4f %-8.1f %s"
              % (pair["campaign"], pair["level"], pair["rho"], pair["rate_base"],
                 pair["rate_rt"], pair["factor"], pair["disjoint"]))
    print("\n%d usable pairs (%d confounded), rho %.2f-%.2f, factor %.0f-%.0fx, "
          "all disjoint %s"
          % (s["pairs"], s["confounded"], s["rho_low"], s["rho_high"],
             s["factor_low"], s["factor_high"], s["all_disjoint"]))
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
