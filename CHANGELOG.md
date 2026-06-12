# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to a modified [Semantic Versioning](https://semver.org/spec/v2.0.0.html) scheme.

---

## [Unreleased] - 2026-06-09

### 🚀 Added
- **S3 Phase Scaffolding**: Complete infrastructure for state staleness corrections
  - `configs/s3_injections.yaml` - Correction injection configuration
  - `scripts/compute_s3_metrics.py` - S3 metrics computation skeleton
  - `scripts/build_paper_s3_outputs.sh` - S3 build script template
  - Kafka producer: planned emit time + optional correction messages (`--s3-mode corrections`)
  - Redis producer: S3 support with `--s3-mode` and `--corrections-every-k` flags
  - Kafka consumer: writes `runs/<run_id>/consumer_events.csv`
  - Redis consumer: per-run consumer group default + run_id filter

### 📚 Documentation
- **Extreme Documentation Overhaul** (This PR)
  - Complete rewrite of project documentation
  - Added comprehensive README.md with:
    - Paper abstract and research objectives
    - Dataset documentation (StatsBomb 2003-2023)
    - Architecture diagrams
    - Detailed methodology
    - Complete experimental phases (S1, S2, S3)
    - Getting started guide
    - Running benchmarks step-by-step
    - Results presentation
    - Reproducibility verification
    - Paper preparation workflow
    - Citation information
  - Added CONTRIBUTING.md with:
    - Contribution guidelines
    - Code standards (Python, shell)
    - Research standards (no-guessing principle)
    - Testing guidelines
    - Development environment setup
    - Release process
  - Added CITATION.cff for automated citation generation
  - Added LICENSE with MIT license + dataset notes
  - Added CHANGELOG.md (this file)

### 🔧 Changed
- `scripts/redis_producer.py` - Enhanced with S3 correction support (uncommitted changes)

### 📊 Results
- All S2 official results remain **frozen and unchanged**
- S3 results infrastructure in place, ready for canonical runs

---

## [0.2.0] - 2025-12-31 - S2 Freeze Final

### ✅ S2 Paper-Official Block Frozen

**This release marks the completion of the S2 phase with all artifacts frozen for paper submission.**

### 🎯 Added
- **Canonical S2 Run List**: `runs/_paper_s2_official_runs.txt` (20 runs)
- **S2 Build Script**: `scripts/build_paper_s2_outputs.sh`
- **Paper Results CSVs** (All committed):
  - `data/processed/results/paper_s2_official.csv`
  - `docs/results/paper_s2_official_by_scenario_summary.csv`
  - `docs/results/paper_s2_official_overall_summary.csv`
  - `docs/results/paper_s2_actionability_windows.csv`
  - `docs/results/paper_s2_meta_matrix.csv`
  - `docs/results/paper_env_snapshot.txt`
- **Plan Comparison Tools**:
  - `scripts/compare_plans.py`
  - Output files: `plan_compare_*.{csv,txt}`
- **Results Table Builder**: `scripts/make_results_table.py`

### 📊 S2 Headline Results

#### TTI p50 Median (ms)
| Scenario | Kafka | Redis | Ratio |
|----------|-------|-------|-------|
| s2sf12 | 173.489184 | 2.507899 | 0.014x |
| s2sf12j2 | 319.164728 | 169.027049 | 0.53x |

#### Missed-Window Rate (Median) - W=100ms
| Scenario | Kafka | Redis |
|----------|-------|-------|
| s2sf12 | 68.41% | 0.00% |
| s2sf12j2 | 91.02% | 72.33% |

### 🏷️ Git Tags
- `paper-s2-freeze` - Initial S2 freeze
- `paper-s2-freeze-final` - Final S2 freeze with all artifacts

### 📝 Commits
- `04ffdcd` - Paper S2: freeze official run set + reproducible outputs + plan comparison
- `7ec6afe` - Paper S2: version canonical official run list
- `0a61710` - Paper S2: archive latest-run lists from 2026-01-01
- `86b14fa` - Add core scripts/configs/docker compose into version control
- `b4f0e65` - Expand .gitignore to ignore local env + generated artifacts

---

## [0.1.0] - 2025-12-30 - S2 Initial Freeze

### 🚀 Initial S2 Freeze

First freeze of S2 results for paper preparation.

### Added
- Initial S2 run lists and results
- Core benchmarking scripts:
  - `kafka_producer.py`, `kafka_consumer.py`
  - `redis_producer.py`, `redis_consumer.py`
  - `compute_tti.py`
  - `summarize_runs.py`
- Runner scripts:
  - `run_s1_blocks.sh`
  - `run_s2_blocks.sh`
  - `run_s2_variant_blocks.sh`
  - `run_kafka_trial.sh`
  - `run_redis_trial.sh`

### S1 Baseline Results
- Kafka baseline runs: 5 replications
- Redis baseline runs: 5 replications
- Results stored in: `data/processed/results/s1_*.csv`

---

## [0.0.1] - 2025-12-28 - Project Inception

### 🌱 Project Setup

Initial project structure and core functionality.

### Added
- Repository structure
- `.gitignore` configuration
- Initial scripts for data fetching and plan generation
- StatsBomb data integration

---

## 📋 Template for Future Releases

### [X.Y.Z] - YYYY-MM-DD

### 🚀 Added
- New features
- New scripts
- New documentation

### 🔧 Changed
- Modified features
- Bug fixes
- Performance improvements

### ❌ Removed
- Deprecated features
- Removed scripts

### 📊 Results
- New benchmark results
- Updated results

### 🏷️ Tags
- New git tags

### 📝 Notes
- Additional notes
- Breaking changes
- Migration instructions

---

## 📖 Versioning Scheme

This project uses a modified semantic versioning scheme:

- **MAJOR** (X): Breaking changes to methodology or results
- **MINOR** (Y): New features, backward compatible
- **PATCH** (Z): Bug fixes, documentation updates

**Pre-release suffixes:**
- `-alpha`: Alpha development
- `-beta`: Beta testing
- `-rc.N`: Release candidate

**Phase suffixes:**
- `-s1`: S1 baseline phase
- `-s2`: S2 paper-official phase
- `-s3`: S3 state staleness phase

---

## 🔗 Related Tags

| Tag | Date | Description |
|-----|------|-------------|
| `paper-s2-freeze` | 2025-12-30 | Initial S2 freeze |
| `paper-s2-freeze-final` | 2025-12-31 | Final S2 freeze with all artifacts |
| `0.1.0` | 2025-12-30 | S2 initial freeze release |
| `0.2.0` | 2025-12-31 | S2 final freeze release |
| `0.3.0-s3-scaffolding` | 2026-01-01 | S3 scaffolding complete |

---

## 📞 Contact

For questions about this changelog or release process:
- Open a GitHub issue
- Email: [your-email@example.com]

---

*Last updated: June 9, 2026*
*Current branch: feat/s3-state-staleness-corrections*
*Current commit: 05c1262*
