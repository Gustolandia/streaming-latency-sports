# Contributing to Streaming Latency Sports Benchmarks

**Thank you for your interest in contributing to this research project!**

This document outlines how to contribute to the *Streaming Latency Benchmarks: Redis Streams vs Kafka for Real-Time Sports Data Feeds* project, targeted for submission to the *Journal of Sports Analytics* (Q1 2026).

---

## 🎯 Contribution Goals

Our primary goal is to produce **reproducible, publishable research** that advances the understanding of streaming systems for real-time sports analytics. Your contributions should align with:

1. **Scientific Rigor** - All claims must be evidence-based and reproducible
2. **No-Guessing Principle** - Every number must trace to a committed artifact
3. **Open Science** - All code, data, and methodology must be transparent
4. **Reproducibility** - Others must be able to regenerate all results

---

## 📋 How to Contribute

### 1. Reporting Issues

Found a bug or have a question? Please [open an issue](https://github.com/[your-org]/streaming-latency-sports/issues) with:

- **Clear title** describing the issue
- **Detailed description** of the problem
- **Steps to reproduce** (if applicable)
- **Expected vs actual behavior**
- **Environment details** (Python version, OS, Docker version)
- **Relevant logs or error messages**

**Issue Templates:**
- `bug_report.md` - For reporting bugs
- `feature_request.md` - For requesting new features
- `question.md` - For general questions

### 2. Suggesting Enhancements

We welcome suggestions for:
- New metrics to compute
- Additional scenarios to test
- Methodology improvements
- Documentation enhancements
- Code optimizations

Please open an issue with:
- Clear description of the enhancement
- Motivation and use case
- Proposed implementation (if you have one)

### 3. Contributing Code

#### Fork & Pull Request Workflow

```bash
# 1. Fork the repository on GitHub
# 2. Clone your fork locally
git clone https://github.com/your-username/streaming-latency-sports.git
cd streaming-latency-sports

# 3. Add upstream remote
git remote add upstream https://github.com/[your-org]/streaming-latency-sports.git

# 4. Create a feature branch
git checkout -b feat/your-feature-name

# 5. Make your changes, commit with clear messages
git commit -m "feat: add description of changes"

# 6. Push to your fork
git push origin feat/your-feature-name

# 7. Open a Pull Request on GitHub
```

#### Branch Naming Conventions

| Type | Prefix | Example |
|------|--------|---------|
| New feature | `feat/` | `feat/s3-correction-metrics` |
| Bug fix | `fix/` | `fix/tti-decomposition-bug` |
| Documentation | `docs/` | `docs/update-readme` |
| Refactoring | `refactor/` | `refactor/kafka-producer` |
| Chore | `chore/` | `chore/update-dependencies` |
| Build | `build/` | `build/add-docker-compose` |
| Hotfix | `hotfix/` | `hotfix/critical-bug` |

#### Commit Message Format

Use structured, descriptive commit messages:

```
# Good examples:
feat: add S3 correction propagation latency metric
fix: correct TTI calculation for out-of-order events
chore: update pip dependencies in requirements.txt
docs: add S3 phase documentation to README
build: add environment snapshot capture to build script

# Bad examples (avoid):
fixed bug
updated stuff
changes
```

Follow [Conventional Commits](https://www.conventionalcommits.org/) guidelines.

---

## 📜 Code Standards

### Python Code

1. **Style**: Follow [PEP 8](https://peps.python.org/pep-0008/) guidelines
   - 4-space indentation
   - Snake_case for variables and functions
   - CamelCase for classes
   - UPPER_CASE for constants
   - Maximum line length: 88 characters (PEP 8 default)

2. **Type Hints**: Use type hints for all public functions and methods
   ```python
   def compute_tti(events: pd.DataFrame, config: dict) -> dict:
       ...
   ```

3. **Docstrings**: Use Google-style docstrings
   ```python
   def compute_tti(events: pd.DataFrame, config: dict) -> dict:
       """Compute Time-to-Insight metrics from event data.
       
       Args:
           events: DataFrame containing event timestamps and processing times
           config: Dictionary with configuration parameters
           
       Returns:
           Dictionary containing TTI percentiles (p50, p95, p99) and IQR
           
       Raises:
           ValueError: If required columns are missing from events
       """
       ...
   ```

4. **Imports**: Group imports by type (standard library, third-party, local)
   ```python
   # Standard library
   import json
   import time
   from pathlib import Path
   
   # Third-party
   import pandas as pd
   import numpy as np
   from kafka import KafkaProducer
   
   # Local
   from .utils import now_ns
   ```

5. **Error Handling**: Use specific exception types and informative messages
   ```python
   if not plan_path.exists():
       raise FileNotFoundError(f"Replay plan not found: {plan_path}")
   
   if speedup <= 0:
       raise ValueError(f"Speedup must be positive, got: {speedup}")
   ```

6. **Logging**: Use Python's `logging` module instead of `print()` for operational messages
   ```python
   import logging
   logger = logging.getLogger(__name__)
   
   logger.debug("Processing event %s", event_id)
   logger.info("Run %s completed in %.2f seconds", run_id, elapsed)
   logger.warning("High latency detected: %s ms", latency)
   logger.error("Failed to process run %s", run_id, exc_info=True)
   ```

### Shell Scripts

1. **Shebang**: Always include `#!/usr/bin/env bash`
2. **Error Handling**: Use `set -euo pipefail` at the start
   ```bash
   #!/usr/bin/env bash
   set -euo pipefail
   ```
3. **Variables**: Quote all variables
   ```bash
   echo "Processing run: $RUN_ID"
   # Not: echo Processing run: $RUN_ID
   ```
4. **Indentation**: 2 or 4 spaces (be consistent within a file)
5. **Comments**: Use `#` for comments, explain non-obvious logic

### File Organization

1. **Script Structure**: Each script should have a clear structure
   ```python
   #!/usr/bin/env python3
   """Module docstring explaining purpose."""
   
   import ...
   
   # Constants
   DEFAULT_SPEEDUP = 120.0
   
   # Functions (in order: helpers first, main logic, then main())
   def helper_function(...):
       ...
   
   def main():
       ...
   
   if __name__ == "__main__":
       main()
   ```

2. **Line Length**: Keep lines under 88 characters for Python, 120 for shell scripts

---

## 🔬 Research Standards

### Reproducibility Requirements

**The No-Guessing Principle**: Every number in the paper must be traceable to a committed artifact.

#### Chain of Custody
```
Paper Claim → Manuscript Number → CSV Cell → Committed CSV File → Build Script → Source Run(s) → Run List → Code Revision
```

#### For All Contributions

1. **New Metrics**: Must include:
   - Clear definition in documentation
   - Computation script
   - Unit tests (if applicable)
   - Example output
   - Integration with build scripts

2. **New Scenarios**: Must include:
   - Scenario definition document
   - Configuration files
   - Run list
   - Expected results description

3. **Bug Fixes**: Must include:
   - Description of the bug
   - Impact assessment (which results affected)
   - Regression test (if applicable)
   - Updated results (if paper-official data affected)

### Data Management

1. **StatsBomb Data**: Use commit hash `3bfbffe1de5750ebd47d770be0bb924a10cde54f` for consistency
2. **Local Data**: Store in `data/raw/statsbomb/`
3. **Processed Data**: Store in `data/processed/`
4. **Results**: Store in `docs/results/` or `data/processed/results/`

### Run Management

1. **Run IDs**: Use descriptive format: `{scenario}_{backend}_rep{num}_{timestamp}`
   - Good: `s2sf12_kafka_rep1_20251230_232006`
   - Bad: `run1`, `test`, `untitled`

2. **Run Metadata**: Always include in `meta.json`:
   ```json
   {
     "run_id": "s2sf12_kafka_rep1_20251230_232006",
     "backend": "kafka",
     "scenario": "s2sf12",
     "plan_path": "data/processed/replay_plans/.../combined_plan.csv",
     "speedup": 120.0,
     "max_t_sim": 600,
     "git": {
       "head": "05c1262",
       "dirty": false
     },
     "env": {
       "python_version": "3.9.13",
       "platform": "Linux-5.15.90.1-microsoft-standard-WSL2"
     },
     "timestamp": "2025-12-30T23:20:06Z"
   }
   ```

3. **Run Artifacts**: Each run folder must contain:
   - `meta.json` - Run metadata
   - `tti_summary.json` - Computed metrics
   - `consumer_events.csv` - Raw consumer output (for S3)

---

## 📊 Testing Guidelines

### Before Submitting a PR

1. **Run existing benchmarks**: Ensure your changes don't break existing functionality
   ```bash
   # Test S2 rebuild
   bash scripts/build_paper_s2_outputs.sh
   
   # Test a single trial
   bash scripts/run_kafka_trial.sh test_run_$(date +%Y%m%d_%H%M%S) data/processed/replay_plans/.../combined_plan.csv
   ```

2. **Validate reproducibility**: Results should be consistent across runs
   ```bash
   # Run same scenario multiple times
   for i in {1..3}; do
       bash scripts/run_kafka_trial.sh test_repro_${i}_$(date +%Y%m%d_%H%M%S) ...
   done
   
   # Compare results
   python scripts/compare_runs.py --runs test_repro_1_*,test_repro_2_*,test_repro_3_*
   ```

3. **Check environment compatibility**: Test in both WSL and native Linux if possible

4. **Verify documentation**: Update any affected documentation

### Code Review Checklist

For reviewers and contributors:

- [ ] Code follows style guidelines
- [ ] All functions have docstrings
- [ ] Type hints are present where applicable
- [ ] Error handling is appropriate
- [ ] Logging is used instead of print()
- [ ] No hardcoded paths or credentials
- [ ] Configuration is externalized
- [ ] Changes are backward compatible (or breaking changes are documented)
- [ ] New dependencies are documented in requirements.txt
- [ ] Documentation is updated
- [ ] No-guessing principle is maintained
- [ ] Reproducibility is preserved

---

## 📚 Documentation Standards

### README.md

The README is the primary documentation. Contributions that affect the workflow should update the README with:

1. **New features**: Add to the appropriate section
2. **Breaking changes**: Clearly document migration path
3. **New scripts**: Add to the Repo Structure section
4. **New metrics**: Add to Core Concepts & Metrics
5. **New phases**: Add to Experimental Phases

### Script Documentation

Each script should have:

1. **Module docstring** at the top
   ```python
   #!/usr/bin/env python3
   """
   Compute Time-to-Insight metrics from consumer event data.
   
   Usage:
       python compute_tti.py --run-id <run_id> --in <input_dir> --out <output_dir>
   """
   ```

2. **Command-line help** via argparse
   ```python
   parser.add_argument('--run-id', required=True, help='Unique run identifier')
   parser.add_argument('--in', dest='input_dir', required=True, help='Input directory')
   parser.add_argument('--out', dest='output_dir', required=True, help='Output directory')
   ```

3. **Example usage** in docstring or comments

### API Documentation

For any public functions that might be used as a library:

1. Include type hints
2. Include comprehensive docstrings
3. Document return types
4. Document raised exceptions
5. Include usage examples

---

## 🔧 Development Environment

### Recommended Setup

| Component | Recommended | Notes |
|-----------|--------------|-------|
| OS | WSL2 (Ubuntu) | Best compatibility |
| Python | 3.9+ | 3.9, 3.10, 3.11 all supported |
| Editor | VS Code | With Python extension |
| Terminal | Windows Terminal | For WSL integration |
| Docker | Docker Desktop | For Windows/Mac |

### Setting Up Development Environment

```bash
# 1. Install WSL2 (Windows only)
wsl --install -d Ubuntu

# 2. Clone repository in WSL
wsl bash -lc 'git clone https://github.com/[your-org]/streaming-latency-sports.git'
cd streaming-latency-sports

# 3. Create virtual environment
python -m venv .venv
source .venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Install development dependencies
pip install -r requirements-dev.txt

# 6. Start services
docker compose up -d

# 7. Verify setup
python scripts/compute_tti.py --help
```

### requirements.txt

```
# Core dependencies
kafka-python>=2.0.0
redis>=4.0.0
pandas>=1.5.0
numpy>=1.21.0

# Optional dependencies
matplotlib>=3.5.0  # For visualization
seaborn>=0.12.0    # For statistical plotting
pyarrow>=8.0.0    # For parquet support
```

### requirements-dev.txt

```
# Development dependencies
pytest>=7.0.0
pytest-cov>=3.0.0
mypy>=0.900
flake8>=4.0.0
black>=22.0.0
isort>=5.10.0

# Documentation
mkdocs>=1.3.0
mkdocs-material>=8.0.0
```

---

## 🎓 Research Paper Contributions

### Adding New Results

If your contribution generates new results for the paper:

1. **Create a canonical run list**
   ```bash
   # Example: runs/_paper_s3_official_runs.txt
   s3_baseline_kafka_rep1_20260101_120000
   s3_baseline_kafka_rep2_20260101_120500
   ...
   ```

2. **Force-add to git** (run lists are normally ignored)
   ```bash
   git add -f runs/_paper_s3_official_runs.txt
   ```

3. **Commit results files**
   ```bash
   git add data/processed/results/paper_s3_official.csv
   git add docs/results/paper_s3_*_summary.csv
   git add docs/results/paper_s3_meta_matrix.csv
   git add docs/results/paper_s3_env_snapshot.txt
   ```

4. **Create build script**
   ```bash
   # scripts/build_paper_s3_outputs.sh
   #!/usr/bin/env bash
   set -euo pipefail
   python scripts/compute_s3_metrics.py
   # ... etc
   ```

5. **Update freeze tags**
   ```bash
   git tag paper-s3-freeze
   git push origin paper-s3-freeze
   ```

### Updating Existing Results

If your change affects existing results (e.g., bug fix in computation):

1. **Document the impact** in the PR description
2. **Rerun all affected scenarios**
3. **Update all derived artifacts**
4. **Create a new freeze tag** if results change significantly
5. **Update the changelog**

---

## 📅 Release Process

### For Maintainers

#### Regular Releases

1. **Update version** (if applicable)
2. **Update CHANGELOG.md**
3. **Run all benchmarks** to verify
4. **Create annotated tag**
   ```bash
   git tag -a v1.0.0 -m "Release v1.0.0: S2 frozen, S3 scaffolding"
   git push origin v1.0.0
   ```

#### Paper Freeze Releases

1. **Verify all artifacts** are committed
2. **Run build scripts** to ensure reproducibility
3. **Create freeze tag**
   ```bash
   git tag -a paper-s2-freeze -m "Paper S2: Freeze official run set"
   git push origin paper-s2-freeze
   ```
4. **Archive run lists**
   ```bash
   cp runs/_paper_s2_official_runs.txt runs/_paper_s2_official_runs_$(date +%Y%m%d).txt
   git add -f runs/_paper_s2_official_runs_$(date +%Y%m%d).txt
   ```

---

## 🤝 Community Guidelines

### Code of Conduct

This project adheres to a **Code of Conduct** that promotes:
- Respectful communication
- Inclusive environment
- Constructive feedback
- Professional behavior

Violations should be reported to [your email].

### Recognition

All contributors will be recognized in:
- The **CONTRIBUTORS.md** file
- The **paper author list** (for significant research contributions)
- The **release notes**

### Contributor License Agreement (CLA)

By contributing to this project, you:
1. Certify that you have the right to contribute the code
2. License your contributions under the MIT License
3. Grant the project maintainers a copyright license to use your contributions

---

## 📞 Getting Help

| Issue | Solution |
|-------|----------|
| Bug report | Open a GitHub issue |
| Feature request | Open a GitHub issue |
| Usage question | Open a GitHub discussion |
| General inquiry | Email [your email] |
| Urgent issue | Email [your email] with "URGENT" in subject |

---

## 📜 Contributor License Agreement

By making a contribution to this project, I certify that:

1. **(a)** The contribution was created in whole or in part by me and I have the right to submit it under the MIT License; or
   **(b)** The contribution is based upon previous work that, to the best of my knowledge, is covered under an appropriate open source license and I have the right under that license to submit that work with modifications, whether created in whole or in part by me, under the same MIT License; or
   **(c)** The contribution was provided directly to me by some other person who certified (a), (b) or (c) and I have not modified it.

2. I understand and agree that this project and the contribution are public and that a record of the contribution (including all personal information I submit with it, including my sign-off) is maintained indefinitely and may be redistributed consistent with this project or the open source license(s) involved.

---

*Last updated: June 9, 2026*
*Thank you for contributing to Streaming Latency Sports Benchmarks!*
