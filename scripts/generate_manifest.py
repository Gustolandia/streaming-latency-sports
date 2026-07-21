#!/usr/bin/env python3
"""
generate_manifest.py
Regenerate reproducibility/MANIFEST.json from the current tree so it never goes stale:
SHA-256 of every code/config file, the current git commit, and a description of the corpora
and fair measurement protocol. Run this after changing any script.

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

# Descriptive record of the corpora + the fair measurement protocol behind the paper.
PROTOCOL = {
    "measurement_fixes": [
        "cross-process clock -> time.time_ns() shared epoch",
        "non-saturating 10x replay (was 120x)",
        "both producers pipelined (Kafka --max-inflight; Redis async worker pool)",
    ],
    "fair_corpus": {
        "latency (windowed, max_t_sim=600)": "concurrency_n{1,5,10,20}_*_{kafka,redis}, single+cluster, 3 reps",
        "decision_staleness (full-match, max_t_sim=9000)": "concurrency_n{1,5,10,20}_*, single, 3 reps, all 40 goals",
    },
    "win_probability": "Skellam proxy; RPS ~= 0.24, ECE = 0.054 over 3239 states (scripts/wp_calibration.py)",
    "dataset": "StatsBomb open data, 1. Bundesliga 2023/24 (comp 9, season 281), 34 matches; "
               "re-fetch via scripts/fetch_statsbomb_events.sh",
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
