# Infrastructure & Reproducibility (Issue 6)

This document specifies the software environment and the reproducibility chain
for the benchmark suite. It complements the per-run provenance recorded in every
`runs/<run_id>/meta.json` and the automated checker
`scripts/verify_reproducibility.py`.

> Hardware note: exact host hardware (CPU model, core count, RAM, storage, NIC)
> is **not** auto-captured in `meta.json` and is intentionally left as a
> fill-in below rather than fabricated. Record the real values before archiving.

---

## 1. Software stack

| Component | Version | Source |
|-----------|---------|--------|
| Apache Kafka | 4.1.1 (KRaft mode) | `apache/kafka:4.1.1` (see `docker-compose*.yml`) |
| Redis | 7.2.4 | `redis:7.2.4` (see `docker-compose-redis-cluster.yml`) |
| Python | 3.9.13 | local interpreter |
| Docker | Docker Desktop | host |
| OS | Windows 11 | host |
| Python deps | pinned | `requirements.txt` |

## 2. Deployment topologies

| Config | Kafka | Redis |
|--------|-------|-------|
| Single | 1 broker, `localhost:9092` (`docker-compose.yml`) | 1 node, `localhost:6379` |
| Cluster | 3 brokers, KRaft, RF=3, ports 9092/9093/9094 (`docker-compose-multibroker.yml`) | 3 nodes, cluster mode, AOF `everysec`, ports 7000–7002 (`docker-compose-redis-cluster.yml`) |

## 3. Host hardware (fill in before archiving)

| Property | Value |
|----------|-------|
| CPU | _e.g. model, cores, base/boost GHz_ |
| RAM | _e.g. 64 GB_ |
| Storage | _e.g. NVMe SSD_ |
| Docker resource limits | _e.g. CPUs / memory allocated to Docker Desktop_ |

## 4. Reproducibility chain (the "no-guessing" principle)

```
Paper number → committed CSV → build/analysis script → canonical run list
            → run directory → meta.json (git SHA + code SHA-256 + config + env)
```

Every run directory contains:

| File | Provenance role |
|------|-----------------|
| `meta.json` | git `head`, per-file `code_sha256`, env capture, topic/stream, config |
| `producer.csv` / `consumer.csv` | raw emit / receive timestamps |
| `tti_summary.json` | computed TTI metrics + `missed_window_rate` |
| `producer.log` / `consumer.log` | process logs |

**Automated verification:**

```bash
python scripts/verify_reproducibility.py --pattern 'batch*' --verbose   # provenance chain
python verify_all_runs.py --pattern 'batch*'                            # file completeness
python deep_health_check_final.py --pattern 'batch*'                    # deep integrity
```

As of the 120-run multi-broker matrix (batches 1–3), all 120 runs pass the
provenance check (`120/120 runs fully reproducible`).

## 5. Reproducing the analysis

```bash
python -m venv .venv && .venv\Scripts\Activate.ps1   # (or: source .venv/bin/activate)
pip install -r requirements.txt

# Multi-broker experiment matrix (single + cluster), if regenerating data:
docker compose -f docker-compose-multibroker.yml up -d
docker compose -f docker-compose-redis-cluster.yml up -d
python run_all_concurrency_tests.py            # orchestrates the batch matrix

# Analyses (read existing runs/ — no Docker needed):
python scripts/analyze_batches_1_2_3.py        # TTI, config, throughput, message size
python scripts/statistical_analysis.py         # Holm-Bonferroni, effect sizes, 95% CIs
python scripts/power_analysis.py --n 20        # a-priori / post-hoc power
python scripts/analyze_protocol_overhead.py    # message size + (de)serialization timing
python scripts/analyze_actionability.py        # sports actionability + production comparison
```

## 6. Permanent archive (Zenodo) — checklist

- [ ] Fill in §3 host hardware.
- [ ] Freeze the branch and tag a release.
- [ ] Bundle: `scripts/`, `tests/`, `configs/`, `docker-compose*.yml`,
      `requirements.txt`, `runs/` (or a documented subset), `data/processed/`,
      `manuscript.tex` + assets, this `docs/` tree.
- [ ] Upload to Zenodo, mint a DOI, add the DOI badge to `README.md`.
