# Reproducibility Package

This directory pins the frozen artefact for the manuscript so its results can be regenerated:
the exact code, environment, datasets and per-run provenance.

**Paper:** [`paper.tex`](../paper.tex) — *When the Interval Is Smaller Than the Instrument: Two
Ways Streaming Latency Benchmarks Fail on Sub-Millisecond Paths* (IEEE `IEEEtran`, targeting
**IEEE TPDS**). This is a **systems / measurement-methodology paper**; the football workload is
the setting that produced the finding, not the contribution. The earlier Journal of Sports
Analytics framing (decision-staleness, Age-of-Information, win-probability) has been **retired**
— do not reintroduce it here.

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

### 5b. Reproduce the mechanism campaigns (broker + a Linux host you can load)

These are the campaigns that decide the mechanism, and they are the only ones that need to
manipulate the machine rather than replay against it. Each is a shell script under
`cloud/campaigns/`; each writes cells into `docs/results/depth/<phase>/` and is analysed by a
script under `scripts/`.

```bash
# Priority at FIXED utilisation: the manipulation that separates scheduling from load.
# Needs sudo for chrt. LEVELS is a comma-separated list of background load percentages.
LEVELS=60,70,75,88,95 bash cloud/campaigns/stamping_priority.sh
python scripts/analyze_occupancy_law.py --out docs/results/model      # L1 floor, L2 ceiling

# Load geometry: same utilisation reached two ways (k cores flat out vs all cores duty-cycled).
OUT=docs/results/depth/ea6 bash cloud/campaigns/load_geometry.sh
python scripts/analyze_knee.py --phases ea6 --depth-dir docs/results/depth \
    --runs-dir runs --out docs/results/model/ea6

# The other side of the inequality: lengthen T_true by padding the payload.
OUT=docs/results/depth/ea10 bash cloud/campaigns/ttrue_sweep.sh
python scripts/analyze_ttrue_sweep.py --depth docs/results/depth/ea10 --runs runs \
    --out docs/results/model
python scripts/fit_tail_index.py --sweep docs/results/model/ttrue_sweep.csv \
    --out docs/results/model                                          # alpha, and whether a mean exists

# The kernel trace. Needs bpftrace and sudo; the campaign refuses to run if its probe
# records fewer than 100 events, because a probe that attaches to an idle machine
# returns zero and zero is the correct answer to the wrong question.
LOAD_PCT=88 OUT=docs/results/depth/ea9 bash cloud/campaigns/stall_distribution.sh
python scripts/analyze_runq_tail.py --depth docs/results/depth/ea9 --runs runs \
    --untraced-base 0.2214 --t-true-ms 0.5 --out docs/results/model
```

**Expect the levels to drift and the effects to hold.** Every one of these has been run at least
twice, and the pattern is consistent: the ratios reproduce, the absolute rates do not. The 88%
ordinary baseline ranges 0.221–0.305 across four campaigns; the geometry contrast at matched
utilisation gives 2.07× and then 2.05×; the tail index gives 0.339 and then 0.344. If your
absolute rates differ from the tables and your ratios do not, that is the expected outcome on
different hardware, not a failed reproduction. See [`docs/laws.md`](../docs/laws.md), which states
each result with the observation that would falsify it.

**One arm is not reproducible and we say so.** The real-time arm of the kernel trace recorded
zero inversions in 2,985 events where every other real-time cell shows ~0.004. We could not
determine whether that arm genuinely differed or tracing perturbed it, no claim in the paper
rests on it, and a reproduction attempt that finds ~0.004 there has not contradicted us.

### 5c. The run index — what survives the raw data

`runs/` held 8.4 GB of per-event CSVs on the Testbed A host and 676 MB more on the Testbed B
driver, and **not one file of it was tracked**. The aggregated CSVs named 1,546 run ids between
them across 57 files; 1,445 local runs appeared in none of them. So the honest answer to "which
runs produced this paper" was a directory on a machine — the same provenance gap Section 7.4 of
the paper reports having found in its own history, reproduced at the level of the repository.

Four tracked files close it, two per testbed, all built by
[`../scripts/build_runs_index.py`](../scripts/build_runs_index.py):

| file | testbed | runs |
|---|---|---|
| `runs_index.csv` · `run_metadata.jsonl.gz` | A (single host) | 1,690 |
| `runs_index_cloud.csv` · `run_metadata_cloud.jsonl.gz` | B (Oracle Cloud driver) | 5,998 |

**7,688 runs, 1.76 MB.** The `.csv` carries one row per run — identity, campaign, backend,
topology, feeds, plan, host, event counts, median transport, and the clock-integrity verdict. The
`.jsonl.gz` carries every `meta.json` verbatim, one JSON per line, including the per-file SHA-256
of the code that run executed.

```bash
python scripts/build_runs_index.py --archive-meta reproducibility/run_metadata.jsonl.gz
python scripts/build_runs_index.py --fast          # skip the raw pass; integrity reads not-assessed
```

**Why the integrity column had to be extracted before anything was deleted.** The audit rejecting
1,321 of 2,266 runs is computed *from* `producer.csv` and `consumer_events.csv`. Delete those and
the number can never be recomputed — it becomes a claim resting on a directory nobody can inspect.
The index keeps, per run, the matched-event count, the negative-transport count, the fraction and
the verdict, so the audit stays checkable run by run after the events themselves are gone.

**This column is transport only, and the paper's audit is not.** The audit applies the same >1%
rule to three components — broker transport, producer scheduling lag and consumer output — and
condemns a run if *any* of them fails. That is where 1,321 of 2,266 comes from, and it lives in
[`../docs/results/integrity_windows/`](../docs/results/integrity_windows/) (Testbed A, 1,382 runs,
862 condemned, 76 conditions) and
[`../docs/results/integrity_by_condition.csv`](../docs/results/integrity_by_condition.csv)
(Testbed B, 884 runs, 459 condemned, 40 conditions). Both recompute exactly from the committed
per-run data.

The index sees only transport, over a different population — every run directory on disk, not the
audited corpora — so it reports 366 of 1,690 locally. **The two numbers are not comparable and
neither is wrong.** The column is called `transport_integrity` rather than `integrity` for that
reason.

`not-assessed` is deliberately **not** a pass:

| verdict | meaning |
|---|---|
| `usable` | ≤1% of matched events negative and a positive median |
| `condemned` | fails that rule |
| `no-matched-events` | the run produced nothing to assess |
| `not-assessed` | raw CSVs absent, or `--fast` was used — not a clean bill |

| | Testbed A | Testbed B |
|---|---|---|
| usable | 1,151 | 1,937 |
| condemned | 366 | 3,976 |
| no matched events | 105 | 44 |
| not assessed | 68 | 41 |
| named by no aggregate | 204 | 5,422 |

**Read the two condemned columns differently.** On Testbed A a condemned run is a failed
measurement. On Testbed B most condemned runs are the mechanism campaigns, which *deliberately*
drive the inversion rate to 10–30% in order to study it — the condemned median negative fraction
there is 0.116 against 0.0000 for the usable runs, a clean bimodal split rather than a quality
problem. A run being condemned means its transport measurement is unusable, not that the run was
wasted.

**The two testbeds record provenance differently, and the index shows which.** Testbed A runs
carry a git commit; Testbed B runs do not, because the driver has no clone — the scripts were
copied to it. Every Testbed B run instead carries the SHA-256 of each script it executed, which
is why the index has both a `git_head` and an `n_code_files` column. An empty `git_head` on a
cloud run is not a missing provenance record; it is a different one.

### 5d. The cloud archive — pulled off the VMs before they are released

Every reported result comes from Testbed B, which is four rented VMs. The indexes above are
summaries; the evidence behind them lived only on `sbl-drv`. It has been pulled down and
verified by SHA-256 against the source:

| archive | contents | compressed |
|---|---|---|
| `cloud_archive/sbl_runs.tgz` | all 5,998 run directories | 95.7 MB (676 MB raw) |
| `cloud_archive/sbl_docs_results.tgz` | the driver's `docs/results`, incl. every depth condition | 15.2 MB (83 MB raw) |
| `cloud_archive/sbl_logs.tgz` | the 24 chain logs | 101 KB |
| `cloud_archive/omb_stdout.log.gz` | the 28 MB OMB run log | 0.4 MB |

`cloud_archive/` is gitignored — it is ~800 MB of raw evidence, and the tracked summary of it is
`runs_index_cloud.csv` plus `run_metadata_cloud.jsonl.gz`. Extraction was verified: 5,998 run
directories out, 5,998 rows in the index.

Three things from it *are* tracked, because they are small and because nothing else records them:

- [`campaign_logs/`](campaign_logs/) — the 24 chain logs, 101 KB, including the ones recording
  campaigns that aborted
- [`../external/omb/`](../external/omb/) — the OpenMessaging Benchmark patch, its output, and the
  configs. The source modification behind Section 6.7 existed only in a working tree on the VM
- `runs_index_cloud.csv`, `run_metadata_cloud.jsonl.gz` — described above

### Which runs anything actually depends on

`used_by` answers a narrower question than it looks like it answers: it flags runs a tracked
aggregate CSV *names*. The campaigns that decide the mechanism name none of theirs. `analyze_knee`,
`analyze_runq_tail`, `analyze_ttrue_sweep` and the rest find their runs by matching a timestamp
taken from a condition directory against `runs/concurrency_<ts>_<backend>_*`, so every run behind
the geometry contrast, the payload sweep and the kernel trace has an empty `used_by`. Reading that
column as "unused" would have selected precisely the load-bearing data for deletion.

[`../scripts/mark_load_bearing.py`](../scripts/mark_load_bearing.py) adds `load_bearing` and
`load_bearing_why`, resolving both routes and recording which one applied:

| | Testbed A | Testbed B |
|---|---|---|
| load-bearing | 1,486 | 5,690 |
| via a named aggregate | 1,486 | 576 |
| via a condition directory | 0 | **5,114** |
| nothing depends on it | 204 | 308 |

The 5,114 in that third row are the runs `used_by` alone would have missed — 90% of everything
the cloud testbed contributes.

**Nothing is pruned on the strength of this.** 512 runs across both testbeds have nothing
depending on them; their summaries stay in the index either way, because "this run happened and
went nowhere" is the fact a directory cleanup destroys and the fact that makes a rejection rate
mean anything.

### 6. Verify the paper agrees with the data

```bash
python -m pytest tests/unit/test_paper_consistency.py -q   # recomputes every headline number
python scripts/verify_reproducibility.py --pattern 'concurrency_n*' --verbose
```

`test_paper_consistency.py` recomputes each figure in `paper.tex` from the CSV that produced it
and fails if the two disagree, so a re-run that changes the data cannot silently desynchronise the
paper.

## Zenodo archival (published)

**Done.** The deposits were published on 2026-08-07 as **v2.0.0**, built from the git tag
`v2.0.0`: code at DOI [10.5281/zenodo.21836305](https://doi.org/10.5281/zenodo.21836305), data at
DOI [10.5281/zenodo.21836326](https://doi.org/10.5281/zenodo.21836326).

`scripts/zenodo_deposit.py` — which built them — remains the tool for future versions. It does
the whole thing in one command: it reads the token from the environment, bundles only git-tracked
files (so the NC-licensed raw StatsBomb events are excluded by design), and **leaves an
unpublished draft** — a published Zenodo record cannot be deleted, so the final click stays a
human decision. The code zip additionally excludes `data/processed/replay_plans/`: the plans are
CC BY-NC derivatives of the StatsBomb data, so the git repository tracks them but the
MIT-licensed zip cannot ship them; they regenerate byte-for-byte with
[`scripts/make_replay_plan.py`](../scripts/make_replay_plan.py) (step 2 above).

```bash
# 0. one-off: create a Personal Access Token at
#    https://zenodo.org/account/settings/applications/  with scopes deposit:write + deposit:actions
#    Put it in your SHELL ONLY -- never in a file in this repo.
$env:ZENODO_API_TOKEN = "..."        # PowerShell   (bash: export ZENODO_API_TOKEN=...)

# 1. rehearse against the sandbox (separate account + token, throwaway DOIs)
python scripts/zenodo_deposit.py --sandbox

# 2. pin the exact state, then upload a real draft (v2.0.0 was built exactly this way)
python scripts/generate_manifest.py
git tag vX.Y.Z && git push --tags
python scripts/zenodo_deposit.py --ref vX.Y.Z

# 3. review the draft in the browser and hit Publish -> the DOI is issued then.
#    (--publish skips the review; irreversible, so only if you are sure.)
```

Then add the new version's DOI to the top-level `README.md` (badge), `CITATION.cff`, and the
manuscript's Artefact Availability statement.
