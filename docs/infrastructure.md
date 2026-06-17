# Infrastructure & Reproducibility (Issue 6)

This document specifies the software environment and the reproducibility chain
for the benchmark suite. It complements the per-run provenance recorded in every
`runs/<run_id>/meta.json` and the automated checker
`scripts/verify_reproducibility.py`.

> Hardware note: host hardware is not auto-captured in `meta.json`; the values in §3
> below were measured on the benchmarking host (June 17 2026). All runs in the corrected
> corpus were produced on this single machine.

---

## 1. Software stack

| Component | Version | Source |
|-----------|---------|--------|
| Apache Kafka | 4.1.1 (KRaft mode) | `apache/kafka:4.1.1` (see `docker-compose*.yml`) |
| Redis | 7.2.4 | `redis:7.2.4` (see `docker-compose-redis-cluster.yml`) |
| Python | 3.9.13 | local interpreter |
| Docker | 29.5.3 (Docker Desktop) | host |
| OS | Windows 11 Home (build 26200) | host |
| Python deps | pinned | `requirements.txt` |

## 2. Deployment topologies

| Config | Kafka | Redis |
|--------|-------|-------|
| Single | 1 broker, `localhost:19092` (`docker-compose.yml`) | 1 node, `localhost:16379`, no persistence |
| Cluster | 3 brokers, KRaft, RF=3, ports 9092/9093/9094 (`docker-compose-multibroker.yml`) | 3 nodes, cluster mode, AOF `everysec`, ports 7000–7002 (`docker-compose-redis-cluster.yml`) |

The single and cluster stacks use disjoint host ports, so they run concurrently.

## 3. Host hardware (measured, June 17 2026)

| Property | Value |
|----------|-------|
| CPU | AMD Ryzen 9 6900HX, 8 cores / 16 threads @ 3.3 GHz |
| RAM | 31.2 GB |
| OS | Windows 11 Home, build 26200 |
| Docker resources | 16 vCPUs, 15.2 GB memory allocated to Docker Desktop |
| Storage | local SSD |

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

## 5. Reproducing the corrected corpus and analysis

The full, current step-by-step procedure (infra bring-up, the corrected
`regenerate_corpus.ps1` / `run_persistence.ps1` / `run_s3_corrected.ps1` orchestrators, the
concurrency runs, and all analyses) lives in
[reproducibility/README.md](../reproducibility/README.md), with the exact pinned commit and
per-file code checksums in `reproducibility/MANIFEST.json`.

Analyses run on existing `runs/` without Docker, e.g.:

```bash
python scripts/statistical_analysis.py      --pattern 'batch9_20260617_*'
python scripts/analyze_protocol_overhead.py --pattern 'batch9_20260617_*'
python scripts/analyze_actionability.py     --pattern 'batch9_20260617_*'
python scripts/power_analysis.py --n 15
```

## 6. Permanent archive (Zenodo) — checklist

- [ ] Fill in §3 host hardware.
- [ ] Freeze the branch and tag a release.
- [ ] Bundle: `scripts/`, `tests/`, `configs/`, `docker-compose*.yml`,
      `requirements.txt`, `runs/` (or a documented subset), `data/processed/`,
      `manuscript.tex` + assets, this `docs/` tree.
- [ ] Upload to Zenodo, mint a DOI, add the DOI badge to `README.md`.
