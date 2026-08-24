"""The consistency audit, derived from the two per-condition integrity files.

Round 16's report claimed these numbers did not reproduce. They do. The reviewer checked them
against `reproducibility/runs_index*.csv`, which is the campaign's *inventory* -- every run
that ever executed, carrying a transport-only verdict -- and not against
`docs/results/integrity_windows/clock_integrity_by_condition.csv` and
`docs/results/integrity_by_condition.csv`, which are the audit's own outputs and reproduce
1,382/862 and 884/459 exactly. `TestAudit` had been asserting both all along.

What the report got right is narrower and still worth fixing. The counts were *typed* into
both documents rather than emitted, which is why the question could arise at all: every other
headline in the paper is a macro whose value is recomputed at build time, and a reader
checking this one had to find the right CSV first. They are macros now.

Two denominators appear in the paper and were never related to each other. The audit runs over
2,266 runs; Table II recounts spans over 5,913. They are different populations -- the audit
covers the conditions a *reported result* rests on, the recount covers every run that produced
matched events on the cloud testbed -- and the main text now says so where the second number
appears.
"""

import csv
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: The audit's own outputs, one row per experimental condition, in the order the manuscript
#: presents the two testbeds.
CORPORA = (
    ("workstation", os.path.join("docs", "results", "integrity_windows",
                                 "clock_integrity_by_condition.csv")),
    ("cloud", os.path.join("docs", "results", "integrity_by_condition.csv")),
)


def read_conditions(path):
    full = path if os.path.isabs(path) else os.path.join(REPO, path)
    if not os.path.exists(full):
        return []
    with open(full, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def corpus_counts(rows):
    """Runs, rejected runs, conditions, and conditions where every run survived.

    A condition is usable only if all of its runs survive, which is the manuscript's rule and
    is already decided in the `usable` column; the run counts are summed from the same rows so
    that the two can never disagree.
    """
    runs = sum(int(r["n_runs"]) for r in rows)
    kept = sum(int(r["n_trustworthy"]) for r in rows)
    usable = sum(1 for r in rows if str(r.get("usable")) == "True")
    return {
        "runs": runs,
        "rejected": runs - kept,
        "conditions": len(rows),
        "usable_conditions": usable,
        "pct": (100.0 * (runs - kept) / runs) if runs else 0.0,
    }


def audit(corpora=CORPORA):
    """Per-testbed counts and their total."""
    out = {name: corpus_counts(read_conditions(path)) for name, path in corpora}
    total = {k: sum(out[n][k] for n in out)
             for k in ("runs", "rejected", "conditions", "usable_conditions")}
    total["pct"] = (100.0 * total["rejected"] / total["runs"]) if total["runs"] else 0.0
    out["total"] = total
    return out


def summary():
    return audit()


def main(argv=None):
    """Print the audit the manuscript's rejection rate is emitted from.

    A function rather than a block under the `__main__` guard: the guard is excluded from
    coverage, and a report loop hidden there is code no test can reach.
    """
    data = audit()
    for name in ("workstation", "cloud", "total"):
        c = data[name]
        print("%-12s runs %-6d rejected %-6d (%.1f%%)  conditions %-4d usable %d"
              % (name, c["runs"], c["rejected"], c["pct"],
                 c["conditions"], c["usable_conditions"]))
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
