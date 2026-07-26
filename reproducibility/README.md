# Reproducibility Package

This directory pins the frozen artefact for the manuscript so its results can be regenerated:
the exact code, environment, datasets and per-run provenance.

**Paper:** [`paper.tex`](../paper.tex) — *A Message Cannot Arrive Before It Is Sent:
Physical-Consistency Auditing for Streaming Latency Benchmarks, and What It Left of a
Kafka-versus-Redis Comparison* (ACM `acmart`, targeting **ACM TOMPECS**). This is a **systems /
measurement-methodology paper**; the football workload is the setting that produced the finding,
not the contribution. The earlier Journal of Sports Analytics framing (decision-staleness,
Age-of-Information, win-probability) has been **retired** — do not reintroduce it here.

- **Git commit:** see [`MANIFEST.json`](MANIFEST.json) (`git_commit`).
- **Environment:** [docs/infrastructure.md](../docs/infrastructure.md) (host hardware, both
  testbeds, Docker/Kafka/Redis/Python versions, deployment topologies).
- **Per-file code checksums:** [`MANIFEST.json`](MANIFEST.json) (`code_sha256`); regenerate with
  `python scripts/generate_manifest.py`.
- **Per-run provenance:** every `runs/<id>/meta.json` (git head, code SHA-256, config); verify
  with `python scripts/verify_reproducibility.py --pattern '<prefix>*' --verbose`.

## What the paper claims, and what the artefact must show

The study set out to compare Apache Kafka and Redis Streams for a real-time football feed under
varying concurrency. The first campaign returned a clean, significant, theory-confirming result
(Redis broker transport rising with concurrency, Kafka flat, *p* = 9.0×10⁻¹¹). **It was an
artefact**, and the artefact here exists to make that legible rather than to hide it.

### The integrity audit (the contribution)

Broker transport is `t_cons_recv_ns − t_broker_ack_ns` — a consumer-process timestamp minus a
producer-process one. A message cannot arrive before it is sent, so a **negative** value is not
noise but proof the instrument failed. [`scripts/clock_integrity.py`](../scripts/clock_integrity.py)
applies that as a stated rule to **every** run, not only the ones that looked wrong:

> A run is **rejected** if more than **1 %** of its events carry a negative value in any latency
> component, or if the **median** of any component is negative. A condition is usable only if all
> of its runs survive. (`TOLERANCE_MS = 0.001`, `MAX_NEGATIVE_FRACTION = 0.01`.) The tool exits
> non-zero, so a campaign script can gate on it.

Applied to all **2,266** runs it rejects **1,321 (58.3 %)**, including every run behind the first
result:

| Corpus | Runs | Rejected | Conditions | Usable | Audit CSV |
|---|---:|---:|---:|---:|---|
| Testbed A (single host, Windows) | 1,382 | 862 (62.4 %) | 76 | 8 | `docs/results/integrity_windows/clock_integrity_by_condition.csv` |
| Testbed B (four Oracle Cloud VMs) | 884 | 459 (51.9 %) | 40 | 13 | `docs/results/integrity_by_condition.csv` |
| **Total** | **2,266** | **1,321 (58.3 %)** | 116 | 21 | |

The threshold is a real decision (the inversion-rate distribution is **not** bimodal — only 104
of 1,382 Testbed A runs are completely clean), so the paper reports its sensitivity rather than
asserting robustness: rejection ranges from **92.5 %** at zero tolerance to **19.2 %** at a
permissive 20 %, and no threshold in that range changes which conditions are usable
(§6.3, `clock_integrity_by_run.csv`).

### Two withdrawals

Both are reported in full, because the paper's argument is what invalid data looks like.

1. **The concurrency finding is withdrawn.** The first result set (Table 1: Redis transport
   1.006 → 1.197 → 1.346 ms across N, Kafka flat, complete rank separation) fails the audit on
   **every** condition behind it. The inversions are invisible in aggregate — 5–14 % of events
   invert, enough to bias a 0.34 ms effect and far too little to disturb any median or interval a
   reviewer inspects.
2. **The twentyfold end-to-end gap is withdrawn.** A Kafka-vs-Redis TTI gap (≈105 ms vs ≈5 ms,
   with ≈103 ms of it producer scheduling lag) was reported, attributed to client code, and built
   into a recommendation. It does **not** reproduce: it is a per-run **start-up cost** read as a
   per-event constant. The runs behind it matched a **median of seven events each**, and Kafka's
   first `produce()` blocks ≈102.6 ms fetching metadata and creating the topic, so the four
   kickoff events due while it blocks inherit that wait. A window sweep settles it by counting
   rather than averaging (§ below). **The integrity check does *not* catch this one** — every
   such run is causally consistent. Causal consistency is necessary, not sufficient.

The audit also removes, as withdrawn arms: the entire Testbed A corpus; the Testbed B accelerated
(non-real-time) concurrency sweep; the connection sweep above ten connections (at N=100 Kafka's
median transport reads **−6.4 ms**); and the three-node cluster arm (0/15 runs, both backends).

### What survives (all from Testbed B, all gated)

- **Broker transport: equivalent within 1 ms, but not a tie.** With each feed carrying a distinct
  real match at true real time, N ∈ {1, 9, 10, 12}, **164 of 201** E1 runs survive; transport is
  flat (Kruskal–Wallis *p* = 0.061 Kafka, 0.091 Redis) and near-equal between systems
  (`docs/results/e1/`). But that E1 comparison is computed over the same **seven-event** opening
  burst as the withdrawn scheduling lag — underpowered and drawn from the least representative part
  of the match: its HL shifts wander (0.021 / 0.116 / 0.053 ms) and its N=1 estimators disagree, so
  it cannot resolve a sub-millisecond difference and the paper does not rest the claim on it.
  A **powered replication** at a verified true-real-time rate, over a **median of 127 events/run**
  (not seven), N ∈ {1, 9, 12} with 15 replicates each (`docs/results/transport_rt/`), resolves what
  E1 could not: Kafka ≈ **0.54 ms** vs Redis ≈ **0.11 ms** — a Hodges–Lehmann shift of **0.41 ms**
  (0.409 / 0.418 / 0.420 at N = 1 / 9 / 12; 90 % CI width ±0.006 ms; *p* < 10⁻²⁶). The two systems
  are **equivalent within 1 ms** at every N under all three estimators (Welch, bootstrap, HL) **yet
  cleanly distinguishable** — Redis's in-memory `XADD` is reproducibly ~0.41 ms faster per
  operation, and the shift is flat across concurrency, so neither degrades. About **0.07 ms** of
  that gap is the H3 asymmetric acknowledgement stamp (the instrument, not the broker), leaving a
  true broker-transport difference near **0.34 ms**. This refines E1 rather than contradicting it,
  and sharpens the contradiction with the withdrawn accelerated corpus, which had reported Redis
  *degrading* with concurrency. Robust to the audit's unequal retention — a worst-case bound holds
  while retention exceeds one half; the tightest cell (N=12) sits at 52.8 %, 2.8 points above
  breakdown ([`scripts/retention_bias.py`](../scripts/retention_bias.py)).
- **The window sweep** that separates a per-run cost from a per-event one
  (`docs/results/window/window_sweep.csv`, [`scripts/analyze_window.py`](../scripts/analyze_window.py)).
  Same match, driver and broker, N=1, true real time, only the window varying. Both arms are
  loop-traced, so the counts come from one instrument:

  | Window | Events emitted | Kafka sched. lag p50 / max | Kafka events >50 ms late | Kafka blocking sends | Redis late / blocking |
  |---:|---:|---|---:|---:|---|
  | 60 s  | 57  | 1.56 / 103.4 ms | **4** | **1** | 0 / 0 |
  | 180 s | 148 | 1.61 / 103.5 ms | **4** | **1** | 0 / 0 |
  | 600 s | 507 | 1.58 / 103.5 ms | **4** | **1** | 0 / 0 |

  Events emitted grow **8.9×**; the affected count does not move, so the share paying the cost
  falls from 7.0 % to 0.8 % — the signature of a once-per-run cost. A per-event constant would
  have grown the count and held the median at 103 ms.
- **The failure model's four rules, measured** (pre-registered, tested on gated conditions;
  `docs/results/model/`, [`scripts/measurement_model.py`](../scripts/measurement_model.py) and
  H3 via [`scripts/analyze_depth.py`](../scripts/analyze_depth.py) → `ec3_stamping.csv`):

  | | Rule | Result |
  |---|---|---|
  | **H1** | inversion rate falls as the measured quantity grows | ✅ ρ = **−0.80**; the robust evidence is the clean contrast (co-located ~0.5 ms fails wholesale, network arm at tens of seconds passes 15/15), *not* the netem slope, which confounds *T*ₜᵣᵤₑ with backlog-driven variance and is not leaned on |
  | **H2** | inversion follows M/G/1 waiting in utilisation | ❌ **refuted** once the sweep reached ρ=0.990, where the candidate forms diverge: M/G/1 fits *worse than the mean* (R² −0.05 vs a fitted exponential's 0.93). The monotone rank correlation survives; the functional form does not |
  | **H3** | asymmetric stamping biases the *comparison* | ✅ gap **+0.286 → +0.215 ms** (−25 %), Kafka 0.392 → 0.322, Redis holds ≈0.106 |
  | **H4** | inversion rises with concurrent process count | ✅ ρ = **+0.80** |

  A construct check (**H8**) rules out the rival explanation that the inversions are independent
  clock quantisation: a Wald–Wolfowitz runs test on the sequence of inversion signs finds them
  strongly **clustered** (median *z* ≈ −6.9 co-located, −6.8 idle, −5.1 saturated — clustering
  present even with no background load), the signature of a shared scheduling delay rather than
  per-event quantisation ([`scripts/analyze_moments.py`](../scripts/analyze_moments.py) →
  `inversion_clustering.csv`, `variance_law.csv`).

- **The configuration result.** Each system has exactly one client-side setting worth one to two
  orders of magnitude, and each documentation example uses the slow value: Kafka producer
  pipelining (`max.in.flight` 1 → 64: 1,644 ms → 16 ms, **103×**) and Redis consumer ack
  batching (per-message `XACK` → 200 at a time: 4,138 ms → 103 ms, **40.2×**). Both are **free on
  a co-located testbed**, so a loopback benchmark certifies as equivalent two clients that differ
  by two orders of magnitude in deployment. (The `tc netem` arm behind the ack-batching mechanism
  passes the audit 15/15 on the Redis side at every injected delay, precisely because its effect
  is tens of seconds — far above the instrument's floor.)

### Rate-provenance disclosure (paper §6.5)

Replay plans built by [`scripts/make_replay_plan.py`](../scripts/make_replay_plan.py) carry a
**baked-in 120× time compression**: `t_emit_offset_s = t_sim_seconds / 120`. So `--speedup 1`
against such a plan is **120×, not real time**; true real time needs `--speedup ≈ 0.008333`
(1/120). The flag's meaning depends on which plan it is pointed at, and getting it wrong is
silent. **No surviving artefact records the achieved replay rate of any reported run**, and the
records that do exist for the earliest (E1) corpus disagree.

Two things follow, both of which the artefact must reflect:

- The reported Testbed B results (E1, and the verified-rate window/replication runs) are at a
  **verified true-real-time rate**, derived from the plan by
  [`scripts/plan_speedup.py`](../scripts/plan_speedup.py) (`--rate 1`) and checked against elapsed
  wall time (`plan_speedup.py --verify <producer.csv> --max-t-sim <window>`), not asserted from a
  flag.
- E1's rate is **recovered from the data, not documented**: 15 Kafka runs that matched exactly
  eight events read a median scheduling lag of **52.34 ms** (range 51.60–53.01), which is the mean
  of a fast and a slow event and so requires exactly four of eight to be late — the count the loop
  trace gives at true real time, and inconsistent with 120× or 1200× (which would read ≈103 ms).
  The audit and both withdrawals are unaffected by the gap either way; the rate is stated as an
  inference throughout.

The lesson the protocol now carries: **record the achieved rate, per run, next to the results —
not the flag that was meant to produce it.**

## Reproduce

The full data-generation pipeline (fetch → plan → replay → audit → analyse) is documented below.
Note that every **reported** number comes from **Testbed B**, four Oracle Cloud VMs on a real
inter-VM network (see [docs/infrastructure.md](../docs/infrastructure.md)); regenerating the raw
per-run corpus therefore needs that infrastructure. The committed per-run data under `runs/` and
the aggregated CSVs under `docs/results/` are the frozen corpus, and the analysis + figure scripts
recompute every table and figure in the paper from them without any broker at all.

```bash
python -m venv .venv && .venv\Scripts\Activate.ps1      # (or source .venv/bin/activate)
pip install -r requirements.txt
```

### 1. Fetch the StatsBomb corpus (pinned)

```bash
python scripts/fetch_statsbomb_corpus.py --dry-run                 # size it first
python scripts/fetch_statsbomb_corpus.py --out data/raw/statsbomb  # pinned commit is inside the script
```

`fetch_statsbomb_corpus.py` replaces the old single-season `fetch_statsbomb_events.sh`: it pulls
the whole modern corpus (52 competition-seasons, 3,315 matches, 2003–2023) keyed to open-data
commit `3bfbffe1de5750ebd47d770be0bb924a10cde54f`. Raw JSON is **not** redistributed (it is
gigabytes, CC BY-NC-4.0); the replay plans derived from it are committed.

### 2. Rebuild the replay plans (regenerable byte-for-byte)

```bash
SHA=3bfbffe1de5750ebd47d770be0bb924a10cde54f
for M in $(ls data/raw/statsbomb/$SHA/events | sed 's/.json//'); do
  python scripts/make_replay_plan.py --commit $SHA --match-id $M --speed-factor 120
done
```

The repo ships eleven `match_<id>/replay_plan.csv` plans under
`data/processed/replay_plans/$SHA/`; `--speed-factor 120` reproduces the committed plans
byte-for-byte (this is the baked-in compression disclosed in §6.5). Each feed in the concurrency
experiment carries a **distinct** real match — an earlier design merged matches into one feed,
which turned the concurrency axis covertly into a throughput axis and is not used.

### 3. Derive and verify the true-real-time replay rate

```bash
PLAN=data/processed/replay_plans/$SHA/match_3895052/replay_plan.csv
python scripts/plan_speedup.py "$PLAN" --rate 1        # prints --speedup ≈ 0.008333 (= 1/120)
# after a run, confirm the achieved rate against wall time (must be ~1.0x):
python scripts/plan_speedup.py "$PLAN" --verify runs/<run_id>/producer.csv --max-t-sim 600
```

### 4. Replay on the multi-host testbed (Testbed B), then audit

```bash
# Distinct match per feed, true real time, Kafka producer pipelined. N is the concurrency;
# --plans-dir hands each feed a different match (the positional plan is only a fallback).
for N in 1 9 10 12; do
  python scripts/run_concurrency_test.py $N "$PLAN" 3 \
    --plans-dir data/processed/replay_plans/$SHA \
    --speedup 0.008333 --max-t-sim 600 \
    --kafka-producer-extra "--max-inflight 64" \
    --kafka-bootstrap <broker>:9092 --redis-host <broker> --redis-port 6379
done

# Apply the consistency check to every run, before looking at any result:
python scripts/clock_integrity.py --runs-dir runs --run-glob 'concurrency_n*' \
    --out docs/results/integrity
```

The **powered transport replication** (Table `tab:transport` in the paper) is the same harness at
the same verified rate, run at N ∈ {1, 9, 12} with 15 replicates and matched over the full match
window (a median of 127 events per run, not the seven-event opening burst the 600 s E1 join kept);
its aggregated output is committed under `docs/results/transport_rt/`.

### 5. Recompute the paper's tables and figures (no broker needed)

```bash
# Surviving comparison + retention bound (E1):
python scripts/retention_bias.py \
    --by-run-csv docs/results/e1/e1_by_run_gated.csv \
    --integrity-csv docs/results/e1/e1_clock_integrity.csv --out docs/results/e1
# The model's rules (H1/H2/H4) and the symmetric-stamping test (H3):
python scripts/measurement_model.py --out docs/results/model
python scripts/analyze_depth.py --depth-dir docs/results/depth --runs-dir runs --out docs/results/model
# The clustering construct check (H8) + variance law that rule out clock quantisation:
python scripts/analyze_moments.py --out docs/results/model
# The window sweep that discriminates per-run from per-event:
python scripts/analyze_window.py --window-dir docs/results/window --runs-dir runs \
    --out docs/results/window/window_sweep.csv
# Workload characterisation (arrival rate, burstiness, kick-off concurrency):
python scripts/characterize_feed.py --events-dir data/raw/statsbomb/$SHA/events   # -> docs/results/football/feed/
python scripts/kickoff_concurrency.py                                             # -> docs/results/football/concurrency/
# Figures, then refresh the manifest:
python scripts/make_paper_figures.py
python scripts/make_e1_figure.py
python scripts/make_window_figure.py
python scripts/generate_manifest.py
```

Run the script with `--help` for the full option set; each writes into `docs/results/`.

### 6. Verify the paper agrees with the data

```bash
python -m pytest tests/unit/test_paper_consistency.py -q   # recomputes every headline number
python scripts/verify_reproducibility.py --pattern 'concurrency_n*' --verbose
```

`test_paper_consistency.py` recomputes each figure in `paper.tex` from the CSV that produced it
and fails if the two disagree, so a re-run that changes the data cannot silently desynchronise the
paper.

## Zenodo archival (needs your Zenodo account token)

`scripts/zenodo_deposit.py` does the whole thing in one command. It reads the token from the
environment, bundles only git-tracked files (so the NC-licensed raw StatsBomb events are excluded
by design), and **leaves an unpublished draft** — a published Zenodo record cannot be deleted, so
the final click stays a human decision.

```bash
# 0. one-off: create a Personal Access Token at
#    https://zenodo.org/account/settings/applications/  with scopes deposit:write + deposit:actions
#    Put it in your SHELL ONLY -- never in a file in this repo.
$env:ZENODO_API_TOKEN = "..."        # PowerShell   (bash: export ZENODO_API_TOKEN=...)

# 1. rehearse against the sandbox (separate account + token, throwaway DOIs)
python scripts/zenodo_deposit.py --sandbox

# 2. pin the exact state, then upload a real draft
python scripts/generate_manifest.py
git tag v1.0-consistency-audit && git push --tags
python scripts/zenodo_deposit.py --ref v1.0-consistency-audit

# 3. review the draft in the browser and hit Publish -> the DOI is issued then.
#    (--publish skips the review; irreversible, so only if you are sure.)
```

Then add the DOI to the top-level `README.md` (badge), `CITATION.cff`, and the manuscript's
Artefact Availability statement.
