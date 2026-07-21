# Reproducibility Package (Issue 6)

This directory documents the frozen, corrected artifact for the manuscript. It pins the
exact code, environment, and datasets so the corrected results can be regenerated.

- **Git commit:** see `MANIFEST.json` (`git_commit`).
- **Environment:** [docs/infrastructure.md](../docs/infrastructure.md) (host hardware,
  Docker/Kafka/Redis/Python versions, deployment topologies).
- **Per-file code checksums:** `MANIFEST.json` (`code_sha256`).
- **Per-run provenance:** every `runs/<id>/meta.json` (git head, code SHA-256, config);
  verify with `python scripts/verify_reproducibility.py --pattern '<prefix>*' --verbose`.

## The fair corpus (primary — pipelined, non-saturating)

The headline results use the **fair** protocol: both producers pipelined (Kafka
`--max-inflight 64`; Redis async worker pool) at a non-saturating `--speedup 10`. Runs are
distinguished by their `meta.json` (`speedup`, `max_t_sim`), not by prefix.

| Dataset | Selector | Purpose |
|---------|----------|---------|
| Latency sweep (windowed) | `speedup=10`, `max_t_sim=600`, single+cluster, N∈{1,5,10,20}, 3 reps | latency vs. N (Kafka flat, Redis grows) |
| Decision-staleness (full-match) | `speedup=10`, `max_t_sim=9000`, single, N∈{1,5,10,20}, 3 reps | all 40 goals → per-match AoI integral |

> Every pre-fix corpus (the `batch9_*` matrix, the 120× concurrency runs, the frozen S2) is
> **superseded** — contaminated by the cross-process clock and/or the Kafka load-generator
> asymmetry. Do not mix them with the fair corpus.

## Reproduce from scratch

```bash
python -m venv .venv && .venv\Scripts\Activate.ps1      # (or source .venv/bin/activate)
pip install -r requirements.txt
bash scripts/fetch_statsbomb_events.sh                  # re-fetch the 34 match JSONs (pinned SHA)

# Single infra (localhost:19092 / 16379):
docker compose -f docker-compose.yml up -d
# Cluster infra (9092-9094 / 7000-7002; distinct ports, can coexist):
docker compose -f docker-compose-multibroker.yml up -d
docker compose -f docker-compose-redis-cluster.yml up -d

# Fair latency sweep (windowed, single infra):
for N in 1 5 10 20; do python scripts/run_concurrency_test.py $N data/processed/replay_plans/s2sf12/combined_plan.csv 3 \
  --speedup 10 --kafka-bootstrap localhost:19092 --redis-port 16379 --kafka-producer-extra "--max-inflight 64"; done
# Full-match decision-staleness sweep (add --max-t-sim 9000):
for N in 1 5 10 20; do python scripts/run_concurrency_test.py $N data/processed/replay_plans/s2sf12/combined_plan.csv 3 \
  --speedup 10 --max-t-sim 9000 --kafka-bootstrap localhost:19092 --redis-port 16379 --kafka-producer-extra "--max-inflight 64"; done

# Analyses (EV = data/raw/statsbomb/<sha>/events):
python scripts/analyze_realtime_concurrency.py --speedup 10 --out docs/results/realtime_concurrency                       # windowed latency
python scripts/analyze_realtime_concurrency.py --speedup 10 --min-max-t-sim 9000 --out docs/results/realtime_concurrency_fullmatch
python scripts/decision_staleness.py --pattern 'concurrency_n*' --min-max-t-sim 9000 --events-dir EV --out docs/results/decision_staleness_fullmatch
python scripts/wp_calibration.py --events-dir EV --out docs/results/win_probability                                        # RPS + ECE
python scripts/fair_statistics.py --by-run docs/results/realtime_concurrency/realtime_concurrency_by_run.csv --value-col tti_p50 --config single --label tti_windowed_single --out docs/results/fair_statistics
python scripts/make_fair_figures.py                                                                                        # figures
python scripts/generate_manifest.py                                                                                        # refresh MANIFEST.json
```

## Zenodo archival (needs your Zenodo account token)

A CLI is installed for this: [`zenodo-client`](https://pypi.org/project/zenodo-client/)
(`pip install zenodo-client`, also in `requirements-dev.txt`). It reads your token from the
environment, so the token never needs to be pasted into a file or shared.

```bash
# 0. one-off: create a Personal Access Token at https://zenodo.org/account/settings/applications/
#    with the "deposit:actions" and "deposit:write" scopes, then export it:
export ZENODO_API_TOKEN=...          # PowerShell:  $env:ZENODO_API_TOKEN="..."

# 1. pin the exact state being archived
python scripts/generate_manifest.py            # refresh MANIFEST.json
git tag v1.0-decision-degradation && git push --tags

# 2. bundle what a reader needs to reproduce the paper
#    (raw StatsBomb events are excluded by design -- re-fetch with fetch_statsbomb_events.sh)
git archive --format=zip --prefix=streaming-latency-sports/ \
    -o streaming-latency-sports-v1.0.zip v1.0-decision-degradation

# 3. create the deposition and mint the DOI (Python API; the CLI covers download/update)
python - <<'PY'
from zenodo_client import Zenodo
z = Zenodo()                      # picks up ZENODO_API_TOKEN
dep = z.create(
    data={
        "metadata": {
            "title": "Latency-induced decision degradation in real-time football analytics",
            "upload_type": "software",
            "description": "Code, replay plans and analysis for the Kafka vs Redis Streams "
                           "decision-staleness study (see README.md).",
            "creators": [{"name": "Ricou, Gustavo Pedro",
                          "affiliation": "Trinity College Dublin"}],
        }
    },
    paths="streaming-latency-sports-v1.0.zip",
)
print("DOI:", dep.json()["doi"])
PY
```

4. Add the returned DOI badge to `README.md` and cite it in `manuscript.tex`
   (the Data/Code Availability statement).
