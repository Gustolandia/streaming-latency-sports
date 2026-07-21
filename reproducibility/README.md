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

# Rebuild the replay plans from the raw events (the repo ships them as data, but they are
# fully regenerable -- make_replay_plan.py reproduces the committed plans byte-for-byte):
SHA=3bfbffe1de5750ebd47d770be0bb924a10cde54f
for M in $(ls data/raw/statsbomb/$SHA/events | sed 's/.json//'); do
  python scripts/make_replay_plan.py --commit $SHA --match-id $M --speed-factor 120
done
# optional: merge several matches into one feed (raises that feed's event rate N-fold)
python scripts/make_multimatch_plan.py --commit $SHA --match-ids-file configs/s2_match_ids.txt \
    --out-dir data/processed/replay_plans/s2sf12 --speed-factor 12

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
python scripts/make_worked_example.py --events-dir EV                                                                      # worked example + figure
python scripts/equivalence_tests.py --by-run docs/results/realtime_concurrency_distinct/realtime_concurrency_by_run.csv --value-col tti_p50 --margin 40 --config single --label tti_distinct --out docs/results/equivalence
python scripts/equivalence_tests.py --by-run docs/results/decision_staleness_distinct/decision_staleness_by_run.csv --value-col decision_staleness_prob_s --n-col n_concurrency --margin 0.04 --config single --label ds_distinct --out docs/results/equivalence
python scripts/wp_sensitivity.py --pattern 'concurrency_n*' --min-max-t-sim 9000 --events-dir EV --out docs/results/wp_sensitivity
python scripts/generate_manifest.py                                                                                        # refresh MANIFEST.json
```

### Distinct-match, throughput and real-time protocols

```bash
PLANS=data/processed/replay_plans/<sha>          # contains match_*/replay_plan.csv
# distinct matches: each feed carries a DIFFERENT real match (--speedup 1 cancels nothing;
# the per-match plans already bake in 120x)
python scripts/run_concurrency_test.py 10 "$FALLBACK" 3 --plans-dir "$PLANS" --speedup 1 --max-t-sim 9000 ...
# throughput sweep: fix N, vary speedup to sweep aggregate events/second
for S in 1 2 4 8 16; do python scripts/run_concurrency_test.py 10 "$FALLBACK" 3 --plans-dir "$PLANS" --speedup $S --max-t-sim 9000 ... ; done
# TRUE real-time: 1/120 cancels the plan's baked 120x (600s of match clock = 10 min wall)
python scripts/run_concurrency_test.py 5 "$FALLBACK" 2 --plans-dir "$PLANS" --speedup 0.008333 --max-t-sim 600 ...
```

## Zenodo archival (needs your Zenodo account token)

`scripts/zenodo_deposit.py` does the whole thing in one command. It reads the token from the
environment, bundles only git-tracked files (so the NC-licensed raw StatsBomb events are
excluded by design), and **leaves an unpublished draft** -- a published Zenodo record cannot be
deleted, so the final click stays a human decision.

```bash
# 0. one-off: create a Personal Access Token at
#    https://zenodo.org/account/settings/applications/  with scopes deposit:write + deposit:actions
#    Put it in your SHELL ONLY -- never in a file in this repo.
$env:ZENODO_API_TOKEN = "..."        # PowerShell   (bash: export ZENODO_API_TOKEN=...)

# 1. rehearse against the sandbox (separate account + token, throwaway DOIs)
python scripts/zenodo_deposit.py --sandbox

# 2. pin the exact state, then upload a real draft
python scripts/generate_manifest.py
git tag v1.0-decision-degradation && git push --tags
python scripts/zenodo_deposit.py --ref v1.0-decision-degradation

# 3. review the draft in the browser and hit Publish -> the DOI is issued then.
#    (--publish skips the review; irreversible, so only if you are sure.)
```

Then add the DOI to `README.md` (badge), `CITATION.cff`, and the manuscript's Data and Code
Availability statement.
