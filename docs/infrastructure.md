# Infrastructure & Reproducibility (Issue 6)

> **Status: this describes Testbed A, whose results the paper withdraws in full.** The hardware
> in §3 is the single Windows host every S-era run was produced on, and the paper's audit rejects
> that entire arm (§7 "What we withdraw"). Every result the paper *reports* comes from Testbed B
> — four Oracle Cloud VMs on a real inter-VM network — which is documented in
> [`cloud/README.md`](../cloud/README.md), not here. The software stack in §1 and the
> reproducibility chain in §4 still apply to both; the host in §3 does not.

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
      `paper.tex` + assets, this `docs/` tree.
- [ ] Upload to Zenodo, mint a DOI, add the DOI badge to `README.md`.


## Release checklist

The suite covers everything that can be decided by reading a file. Three things cannot, and
each has cost a referee round, so they are written down rather than remembered.

**1. Look at every figure, at the size it prints.** Rasterise the figure directory to a contact
sheet and read it. Two defects reached referees this way and neither was visible to any gate,
because both were layout rather than content:

- Figure 5(b): the `32 KB` label was struck through by the half-cell rule (round 12).
- `window_sweep`: `set_xticks` replaces a log axis's *major* ticks and leaves the minor decade
  formatter running, so "180" printed underneath "2 x 10^2" on both panels (round 13).

Font, Type 3, family and text-layer gates all passed both. A collision is a fact about
geometry, and only an eye or a pixel-diff sees it.

**2. Read the reference list as a copy editor would.** Round 14 was the first time anyone did,
and it found three defects in a list that is otherwise scrupulous: one entry printing its URL
twice, two venues unabbreviated among forty-three that were not, and the arXiv entries split
across two conventions. `TestReferenceHouseStyle` now catches those three classes; it does not
catch a mis-spelled author or a wrong page range.

**3. Confirm an unexpected test result before explaining it.** Three times now the failure mode
has been to reason about an unexpected result from the apparatus instead of opening the file:
a `sed` mutation that silently matched nothing and made a live gate look inert (twice), and a
new gate that fired on a real defect and was narrowed on the assumption of a false positive
(round 12, corrected in round 13). Verify the mutation applied. Open the file the gate names.
An unexpected result from the apparatus deserves the scrutiny this paper asks for an unexpected
measurement.
