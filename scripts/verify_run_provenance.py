#!/usr/bin/env python3
"""
verify_run_provenance.py
Does every number the paper quotes come from a run that actually happened?

This check exists because the paper failed it. Section 6.7 reported that the instrumented
OpenMessaging Benchmark "discarded zero samples" and treated that as a bounded negative. The run
behind it had died four seconds in on a missing argument and measured nothing at all; the script
wrote a zero because a benchmark that never runs discards nothing. The number looked exactly like
a measurement, passed every consistency test we had, and reached a draft.

The consistency tests answer "does the paper agree with the CSV". They cannot answer "did the CSV
come from anything", and those are different questions. A file can be perfectly consistent with a
manuscript and still describe an experiment that never took place.

WHAT COUNTS AS EVIDENCE THAT A RUN HAPPENED. Not the file existing, and not the numbers looking
plausible. One of:

    an event count      n_events, n, or similar, greater than zero
    a run count         n_runs greater than zero
    an explicit gate    a `valid` column the producing script sets only after checking output
    a sample size       n_base/n_rt style counts on a comparison

An artefact carrying a quantity but NO evidence of sample size is the dangerous case: it is
exactly the shape the OMB zero had. Those are reported as UNVERIFIABLE rather than as passing,
because "we cannot tell" is the honest verdict and it is what a reader would want flagged.

CLI:
    python scripts/verify_run_provenance.py --results docs/results
"""
import argparse
import csv
import re
from pathlib import Path

# Columns whose presence and positivity witness that events were actually observed.
COUNT_COLUMNS = ("n_events", "n_runs", "n", "n_base", "n_rt", "n_matched", "events",
                 "n_produced", "n_consumed", "count", "pub_lines", "traced_events",
                 "n_high", "n_idle", "n_floor", "n_samples", "samples",
                 # Added after the first pass called window_sweep.csv unverifiable: it carries
                 # `runs` and `events_per_run`, which are sample sizes under different names.
                 # A checker that misses them raises a false alarm, and false alarms are how a
                 # check stops being read.
                 "runs", "events_per_run", "trace_runs", "trace_events",
                 # colocation.csv records its counts per arm. Same lesson as above, one campaign
                 # later: the sample size was present and the checker did not recognise the name.
                 "n_remote", "n_colocated")

# Artefacts that are not measurements at all. A source audit's provenance is a file, a line and
# a commit, not a sample size, and demanding a run count of it would be a category error. It is
# checkable in its own way -- a reader can open the named line in the named commit -- so it is
# reported separately rather than lumped in with unverifiable measurements.
SOURCE_AUDITS = {"external/harness_audit.csv"}

# Derived artefacts: computed FROM another artefact rather than from a run of their own. Their
# provenance is inherited, and stating the source explicitly is the point -- it makes the chain
# checkable instead of assumed. An entry here whose source is not itself verified is a failure.
DERIVED = {
    "model/separability.csv": "model/collapse_points.csv",
    "model/two_state_fit.csv": "model/collapse_conditions.csv",
    "model/fdelta_reproduction.csv": "model/collapse_conditions.csv",
    "e1/e1_transport_kruskal_across_n.csv": "e1/e1_by_run_gated.csv",
    "football/concurrency/concurrency_summary.csv": "football/feed/feed_summary.csv",
    # The tail index is a fit over the payload sweep; it has no runs of its own, and the
    # n_points it does carry describes the fit rather than a sample.
    "model/tail_index.csv": "model/ttrue_sweep.csv",
    "model/ea10b/tail_index.csv": "model/ea10b/ttrue_sweep.csv",
    # L1/L2 are computed over the priority campaigns; the counts live in those files.
    "model/occupancy_law.csv": "model/stamping_priority.csv",
}
# An explicit validity gate set by the producing script after checking for real output.
VALID_COLUMNS = ("valid",)
NUMERIC = re.compile(r"^-?\d+(\.\d+)?([eE][-+]?\d+)?$")


def evidence_for(path):
    """What witnesses that this artefact came from a run? Returns (verdict, detail)."""
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    except (OSError, UnicodeDecodeError) as exc:
        return "UNREADABLE", str(exc)
    if not rows:
        return "EMPTY", "no data rows"

    cols = set(rows[0].keys())

    # An explicit gate is the strongest witness: the producing script checked for output.
    gate = next((c for c in VALID_COLUMNS if c in cols), None)
    if gate:
        bad = [r for r in rows if str(r.get(gate, "")).strip() not in ("1", "True", "true")]
        if bad:
            return "INVALID", f"{len(bad)}/{len(rows)} rows marked {gate}!=1"
        return "VERIFIED", f"{gate}=1 on all {len(rows)} rows"

    # Otherwise a positive sample size somewhere in the file. Matched by prefix as well as by
    # exact name: artefacts that compare two things name their counts n_runs_kafka,
    # n_events_redis and so on, and an exact-match list silently missed all of them.
    found = []
    candidates = [c for c in cols
                  if c in COUNT_COLUMNS
                  or c.startswith(("n_runs", "n_events", "n_samples"))]
    for c in sorted(candidates):
        if c not in cols:
            continue
        vals = []
        for r in rows:
            v = str(r.get(c, "")).strip()
            if NUMERIC.match(v):
                vals.append(float(v))
        if vals and max(vals) > 0:
            found.append(f"{c}<=" + f"{int(max(vals)):,}")
    if found:
        return "VERIFIED", "; ".join(found[:3])
    return "UNVERIFIABLE", f"{len(rows)} rows, no sample-size or validity column"


def scan(results_dir, cited):
    out, direct = [], {}
    for rel in sorted(cited):
        p = Path(results_dir) / rel
        if not p.exists():
            out.append({"artefact": rel, "verdict": "MISSING", "detail": "file not present"})
            continue
        verdict, detail = evidence_for(p)
        direct[rel] = verdict
        out.append({"artefact": rel, "verdict": verdict, "detail": detail})

    # Second pass: reclassify audits and derived artefacts, now that the direct verdicts of
    # their sources are known.
    for row in out:
        rel = row["artefact"]
        if rel in SOURCE_AUDITS:
            row["verdict"] = "AUDIT"
            row["detail"] = "source audit: provenance is file+line at a named commit, not a run"
        elif rel in DERIVED and row["verdict"] == "UNVERIFIABLE":
            src = DERIVED[rel]
            srcv = direct.get(src)
            if srcv is None:
                p = Path(results_dir) / src
                srcv = evidence_for(p)[0] if p.exists() else "MISSING"
            if srcv in ("VERIFIED", "DERIVED"):
                row["verdict"] = "DERIVED"
                row["detail"] = f"computed from {src}, which is {srcv}"
            else:
                row["verdict"] = "UNVERIFIABLE"
                row["detail"] = f"computed from {src}, which is {srcv}"
    return out


def cited_artefacts(test_file):
    """Every artefact the paper's consistency tests read, i.e. every one it quotes from."""
    text = Path(test_file).read_text(encoding="utf-8")
    cited = set()
    for m in re.finditer(r'_rows\(((?:\s*"[^"]+"\s*,?)+)\)', text):
        parts = re.findall(r'"([^"]+)"', m.group(1))
        if parts:
            cited.add("/".join(parts))
    return cited


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default="docs/results")
    ap.add_argument("--tests", default="tests/unit/test_paper_consistency.py")
    ap.add_argument("--out", default="docs/results/provenance.csv")
    args = ap.parse_args(argv)

    cited = cited_artefacts(args.tests)
    if not cited:
        print("no cited artefacts found; is the test file path right?")
        return 1
    rows = scan(args.results, cited)

    order = {"MISSING": 0, "INVALID": 1, "UNVERIFIABLE": 2, "EMPTY": 3, "UNREADABLE": 4,
             "AUDIT": 5, "DERIVED": 6, "VERIFIED": 7}
    rows.sort(key=lambda r: (order.get(r["verdict"], 9), r["artefact"]))
    print(f"{'verdict':>13}  artefact")
    for r in rows:
        print(f"{r['verdict']:>13}  {r['artefact']}")
        if r["verdict"] != "VERIFIED":
            print(f"{'':>13}    {r['detail']}")

    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    print("\n== summary ==")
    for k in sorted(counts, key=lambda x: order.get(x, 9)):
        print(f"  {k:>13}: {counts[k]}")

    bad = [r for r in rows if r["verdict"] in ("MISSING", "INVALID", "EMPTY", "UNREADABLE")]
    unver = [r for r in rows if r["verdict"] == "UNVERIFIABLE"]
    print()
    if bad:
        print(f"{len(bad)} artefact(s) the paper quotes cannot be trusted as measurements.")
    if unver:
        print(f"{len(unver)} artefact(s) carry no sample size, so we cannot tell whether the")
        print("run behind them happened. That is the shape the OMB zero had.")
    if not bad and not unver:
        print("Every quoted artefact carries evidence that its run produced data,")
        print("is derived from one that does, or is a source audit checkable at its commit.")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["artefact", "verdict", "detail"])
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {out}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
