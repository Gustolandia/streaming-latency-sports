# Reproducibility Package (Issue 6)

This directory documents the frozen, corrected artifact for the manuscript. It pins the
exact code, environment, and datasets so the corrected results can be regenerated.

- **Git commit:** see `MANIFEST.json` (`git_commit`).
- **Environment:** [docs/infrastructure.md](../docs/infrastructure.md) (host hardware,
  Docker/Kafka/Redis/Python versions, deployment topologies).
- **Per-file code checksums:** `MANIFEST.json` (`code_sha256`).
- **Per-run provenance:** every `runs/<id>/meta.json` (git head, code SHA-256, config);
  verify with `python scripts/verify_reproducibility.py --pattern '<prefix>*' --verbose`.

## Corrected datasets (post clock + producer fixes)

| Dataset | Run prefix | Runs |
|---------|-----------|------|
| Multi-broker matrix (RQ1, Issue 2) | `batch9_20260617_*` | 60 |
| Persistence (H31/H32) | `batch9p_20260617_*` | 12 |
| S3 corrections | `s3c_20260617_*` | 30 |
| Concurrency (RQ2, true N-feed) | `concurrency_n*_20260617_16*` | 70 |

> All runs dated before 2026-06-17 are contaminated by the cross-process clock bug and were
> removed; do **not** mix them with the corrected corpus.

## Reproduce from scratch

```bash
python -m venv .venv && .venv\Scripts\Activate.ps1      # (or source .venv/bin/activate)
pip install -r requirements.txt

# Cluster infra (RQ1 cluster + Redis cluster):
docker compose -f docker-compose-multibroker.yml up -d
docker compose -f docker-compose-redis-cluster.yml up -d
# Single infra (RQ1 single, persistence, S3, concurrency) — distinct ports, can coexist:
docker compose -f docker-compose.yml up -d

# Regenerate the corrected corpus:
pwsh scripts/regenerate_corpus.ps1 -Phase cluster
pwsh scripts/regenerate_corpus.ps1 -Phase single
pwsh scripts/run_persistence.ps1
pwsh scripts/run_s3_corrected.ps1
python scripts/run_concurrency_test.py 5  data/processed/replay_plans/s2sf12/combined_plan.csv 1 --kafka-bootstrap localhost:19092 --redis-port 16379 --broker-count 1
python scripts/run_concurrency_test.py 10 data/processed/replay_plans/s2sf12/combined_plan.csv 1 --kafka-bootstrap localhost:19092 --redis-port 16379 --broker-count 1
python scripts/run_concurrency_test.py 20 data/processed/replay_plans/s2sf12/combined_plan.csv 1 --kafka-bootstrap localhost:19092 --redis-port 16379 --broker-count 1

# Analyses:
python scripts/statistical_analysis.py     --pattern 'batch9_20260617_*' --out docs/results/corrected_statistical_analysis
python scripts/analyze_protocol_overhead.py --pattern 'batch9_20260617_*' --out docs/results/corrected_protocol_overhead
python scripts/analyze_actionability.py     --pattern 'batch9_20260617_*' --out docs/results/corrected_actionability
python scripts/compute_s3_metrics.py        # runs/_paper_s3_official_runs.txt -> paper_s3_official.csv
```

## Zenodo archival (requires your account — not automatable here)

1. Verify the working tree is clean and tagged: `git tag v1.0-corrected && git push --tags`.
2. Bundle: `scripts/`, `tests/`, `configs/`, `docker-compose*.yml`, `requirements.txt`,
   `data/processed/`, `runs/` (corrected `*_20260617*` + `batch9*` only), `manuscript.tex`
   + assets, `docs/`.
3. Upload to Zenodo, mint a DOI, and add the DOI badge to `README.md`.
