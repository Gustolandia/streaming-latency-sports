#!/usr/bin/env python3
"""
generate_manifest.py
Regenerate reproducibility/MANIFEST.json from the current tree so it never goes stale:
SHA-256 of every code/config file, the current git commit, and a description of the corpus
and the measurement protocol behind the paper. Run this after changing any script.

CLI:
    python scripts/generate_manifest.py [--root .] [--out reproducibility/MANIFEST.json]
"""
import argparse
import glob
import hashlib
import json
import os
import subprocess
from datetime import date
from pathlib import Path

# Globs (relative to --root) whose SHA-256 pins the reproducible pipeline.
CODE_GLOBS = ["scripts/*.py", "configs/*.yaml", "docker-compose*.yml", "requirements.txt"]

# Descriptive record of the corpus + the measurement protocol behind the paper
# (When the Interval Is Smaller Than the Instrument, IEEE TPDS). Kept in sync with
# reproducibility/README.md and paper.tex; the JSA framing (decision-staleness / win-probability)
# and the earlier ACM TOMPECS framing are retired and must not be reintroduced here.
PROTOCOL = {
    "paper": "When the Interval Is Smaller Than the Instrument: Two Ways Streaming Latency "
             "Benchmarks Fail on Sub-Millisecond Paths (IEEE TPDS). The Journal of Sports "
             "Analytics framing (decision-staleness / Age-of-Information / win-probability) is "
             "retired, as is the earlier ACM TOMPECS formatting.",
    "integrity_audit": "scripts/clock_integrity.py rejects a run when >1% of its events invert "
                       "(negative transport or scheduling lag) or any component median is "
                       "negative; applied to all 2266 runs, 1321 rejected (58.3%).",
    "measurement_fixes": [
        "cross-process clock -> time.time_ns() shared epoch",
        "verified true real-time replay (--speedup derived from the plan by plan_speedup.py, "
        "~0.008333 = 1/120; achieved rate checked against elapsed wall time)",
        "both producers pipelined (Kafka --max-inflight; Redis async worker pool)",
        "distinct real match per feed (--plans-dir), so concurrency is not covertly throughput",
    ],
    "reported_corpus": {
        "testbed": "Testbed B, four Oracle Cloud VMs on a real inter-VM network; every reported "
                   "number passes clock_integrity.py",
        "E1 transport (true real-time, N in {1,9,10,12})": "docs/results/e1/, 164/201 runs "
            "retained; transport flat and near-equal, but underpowered (median 7 events/run), so "
            "the equivalence claim does not rest on it",
        "powered transport replication (verified real-time, N in {1,9,12}, 15 reps, median 125 "
        "matched events/run, audit-gated)": "docs/results/transport_rt/ and transport_rt2/, "
            "*_gated.csv; Kafka ~0.54 ms vs Redis ~0.11 ms, HL shift 0.41 ms (p<1e-26): "
            "equivalent within 1 ms but not a tie -- Redis reproducibly faster and flat across "
            "concurrency; ~0.07 ms of the gap is the H3 asymmetric stamp. The primary artefacts "
            "are gated: the ungated originals had consumed audit-condemned runs; re-admitting "
            "them moves the shift by at most 0.003 ms (0.017 in the replication).",
        "window sweep (per-run vs per-event start-up cost)": "docs/results/window/window_sweep.csv",
        "E1 reconciliation (E1-REP)": "docs/results/e1_rep/e1_replication.csv; the SAME powered "
            "runs give the 0.41 ms shift over all events and E1's near-equality over their first "
            "seven in emission order (0.088/0.129/0.248 ms), matching E1 in absolute level too. "
            "E1 measured the opening burst; its transport row is re-labelled, not withdrawn",
        "knee resolution (E-A4)": "docs/results/depth/ea4/; a duty-cycle load ladder "
            "(stress-ng --cpu-load) reaching achieved rho 0.8812/0.9204/0.9501/0.9701/0.9900, "
            "which is where M/G/1 and the bounded alternatives diverge ~8x. The earlier ladder "
            "stopped at 0.878 and everything above collapsed onto a degenerate rho=1.000, which "
            "is why the M/G/1 form could not be falsified before",
        "stamping priority (E-A5)": "docs/results/depth/ea5/; occupancy moved via SCHED_FIFO on "
            "the stamping processes at unchanged utilisation, to separate an occupancy mechanism "
            "from a utilisation one. sched_verification.txt records that the manipulation applied "
            "(20 python3 at SCHED_FIFO 80; the SCHED_OTHER entries are their sudo parents). The "
            "analysis withholds any comparison whose two arms differ in rho by more than 5 points",
        "model rules H1/H2/H3/H4 + H8 clustering construct check": "docs/results/model/ "
            "(measurement_model.py, analyze_depth.py, analyze_moments.py)",
        "load-dependence model selection": "docs/results/model/two_state_fit.csv and "
            "two_state_prediction.csv (fit_two_state.py). The two-state form P = p(rho)*S has no "
            "content on the rho axis with p free -- any monotone rate curve can be written that "
            "way -- and the variant that does fit leads only because it reads sigma and mu: "
            "freezing sigma IMPROVES the fit (residual ratio 0.19), because sigma and rho are "
            "collinear on this ladder. Reported as unidentified, not supported",
        "audit": "docs/results/integrity_windows/ (Testbed A) and "
                 "docs/results/integrity_by_condition.csv (Testbed B)",
    },
    "withdrawn": [
        "the concurrency finding (Redis transport rising with N, Kafka flat, p=9.0e-11): every "
        "run behind it fails the audit",
        "the 20x end-to-end gap: a per-run start-up cost read as a per-event constant (the runs "
        "matched a median of 7 events); the audit does NOT catch this one",
        "the entire Testbed A corpus, the accelerated concurrency sweep, the connection sweep "
        "above 10 connections, and the 3-node cluster arm",
        "the M/G/1 functional form for H2: refitting against a power law and an exponential "
        "found the exponential fits the published table BETTER (R2 0.961 vs 0.945). Only the "
        "shape survives -- superlinear growth with a knee near saturation",
        "H1's intermediate effect-size points: the E-B2 sweep FAILED its own manipulation check. "
        "netem at the broker is common-mode -- it delays the acknowledgement path and the "
        "delivery path equally, so it cancels in the difference that defines transport. TTI "
        "tracked the injection (3.72 -> 23.61 ms) while transport stayed flat (0.535 -> 0.480). "
        "The co-located-versus-network contrast survives, because it needs no manipulation",
    ],
    "rate_provenance": "No surviving artefact records an achieved replay rate; plans carry a "
                       "baked-in 120x compression, so --speedup 1 means 120x rather than real "
                       "time. The reported cloud runs are at a verified true-real-time rate; "
                       "E1's rate is recovered from a 52.34 ms diagnostic cell. See paper "
                       "the audit section.",
    "dataset": "StatsBomb open data, 52 competition-seasons / 3,315 matches (2003-2023), pinned "
               "to commit 3bfbffe1de5750ebd47d770be0bb924a10cde54f; re-fetch via "
               "scripts/fetch_statsbomb_corpus.py. Eleven per-match replay plans are committed "
               "under data/processed/replay_plans/<sha>/.",
}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_hashes(root, globs=CODE_GLOBS):
    """Map repo-relative path -> sha256 for every file matching the globs, sorted."""
    root = Path(root)
    out = {}
    for pattern in globs:
        for p in sorted(glob.glob(str(root / pattern))):
            if os.path.isfile(p):
                rel = os.path.relpath(p, root).replace(os.sep, "/")
                out[rel] = sha256_file(p)
    return out


def git_commit(root):
    try:
        return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=10).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def build_manifest(root):
    hashes = collect_hashes(root)
    return {
        "git_commit": git_commit(root),
        "generated": date.today().isoformat(),
        "environment": "see docs/infrastructure.md",
        "protocol": PROTOCOL,
        "n_code_files": len(hashes),
        "code_sha256": hashes,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Regenerate reproducibility/MANIFEST.json")
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", default="reproducibility/MANIFEST.json")
    args = ap.parse_args(argv)

    manifest = build_manifest(args.root)
    if not manifest["code_sha256"]:
        print(f"No code files found under {args.root}")
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {out} with {manifest['n_code_files']} files at commit {manifest['git_commit'][:8]}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
