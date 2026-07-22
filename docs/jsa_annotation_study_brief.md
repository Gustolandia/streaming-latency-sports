# Agent brief: measuring live football event-feed freshness (JSA paper 2)

> **SUPERSEDED — not recommended.** This brief was written to rescue a Journal of Sports
> Analytics outcome from the streaming-latency work. On checking the literature it does not hold
> up: the general question (how stale data degrades inference) is a mature Age-of-Information
> literature, and football is close to the worst sport to ask a latency question about, because
> its win probability is driven by two or three discrete events per match. Retained as a record
> of the reasoning, not as a plan. See the README for why the systems framing was chosen instead.

Copy everything below the line into a fresh agent session. It is written to stand alone.

---

## Objective

Measure, for the first time in the peer-reviewed literature, **how long it takes for an event on
a football pitch to become available to a consumer of a commercial live data feed** — and how
much that differs between providers.

This is the dominant term in the end-to-end staleness budget of the companion paper
(`manuscript.tex` in this repo), which measured the *transport* term at ~1 ms and showed it is
0.0003% of what a decision-maker experiences. The remaining ~99.99% is annotation and
distribution, and nobody has measured it. Liu et al. (2013, *Int. J. Performance Analysis in
Sport* 13(3):803–821) measured operator *accuracy* — inter-operator agreement κ ≈ 0.92, event
time agreement 0.06 ± 0.04 s — but never latency.

**Target journal: Journal of Sports Analytics.** The readership is club/federation analysts,
sports statisticians, and betting/broadcast practitioners. Every design decision should be
judged by "does this change what such a reader does?"

## The research questions

- **RQ1** How stale is a live football event feed when it reaches a consumer? Report a
  distribution, not a point estimate.
- **RQ2** How much do commercial providers differ from each other on the same match and the
  same event?
- **RQ3** Does staleness vary by event type (goal, red card, substitution, corner), by
  competition tier, or with match congestion (many simultaneous fixtures)?
- **RQ4** What does the measured staleness imply for in-play decisions — specifically, for how
  long does a consumer hold a materially wrong win-probability estimate?

## Design

### Primary measurement: cross-provider differential (no ground truth needed)

Poll **two or three providers simultaneously** for the same live matches. For each event,
record the wall-clock time at which each provider first exposes it. The difference between
providers is a pure pipeline difference and needs no knowledge of when the action actually
happened. This is the robust core of the paper and should be the headline.

### Secondary measurement: absolute staleness (assumption-laden, report as such)

Compare first-appearance wall-clock time against `kickoff_wall_clock + reported_match_minute`.
This gives an absolute estimate but assumes the match clock tracks elapsed real time, which
stoppages break. Bound the error explicitly: use only first-half events before the first
stoppage where possible, and report the assumption prominently. **Do not lead with this
number.**

### What to poll

- Poll frequency must be well below the effect you are measuring. If providers update every
  15 s, poll at 2–5 s so the quantisation is not the measurement.
- Record the raw HTTP response and a local receive timestamp for every poll, so the analysis
  can be redone without re-collecting.
- Log poll dispatch time and response time separately — your own request latency must not be
  attributed to the provider.

## Feasibility, already checked (July 2026)

- **Fixtures are available now.** UEFA Champions/Europa/Conference League qualifying runs
  9 July – 27 August 2026. Domestic leagues resume from 21 August (Premier League).
- **APIs.** API-Football updates live events every ~15 s; its free tier is 100 requests/day,
  which is too thin for continuous polling (a 90-minute match at 5 s needs ~1,100 requests) —
  budget a modest paid tier. TheStatsAPI and Live-Score API are alternatives with higher rate
  limits. football-data.org's free tier is explicitly *delayed* and is therefore unusable for
  this study, though it may serve as a deliberately-slow third arm.
- **Cost.** Expect ~€25–60/month across two or three providers for one season-opening month.
  Confirm each provider's terms of service permit this use and cite them.

## Hard requirements

1. **Check the Terms of Service of every provider before collecting.** Some prohibit
   redistribution or benchmarking. If a provider's ToS forbids it, do not use that provider and
   say so in the paper. Do not publish raw feed contents; publish derived timings only.
2. **No fabricated citations.** A bibliography audit of the companion paper found ten entries
   that do not exist. Verify every reference against the publisher, arXiv, or DOI record before
   citing it, and keep a note of what you checked.
3. **Test coverage:** every new script needs ≥95% branch coverage, target 100%, matching the
   existing standard in `tests/unit/`.
4. **Honest reporting:** if a measurement fails an integrity check, report it and the retention
   rate. Reuse `scripts/clock_integrity.py`'s posture — a stated rule, applied uniformly, with
   the rejection rate reported like a survey response rate.
5. **Pre-register the analysis** (even informally, as a committed file with a timestamp) before
   collecting data. The companion paper's central lesson is how easily a plausible result
   survives when the analysis is chosen after seeing the data.

## Reusable assets in this repo

- `scripts/clock_integrity.py` — the physical-consistency check and its rule.
- `scripts/staleness_budget.py` — the annotation/delivery/inference budget; this study supplies
  the term it currently sweeps.
- `scripts/win_probability.py`, `scripts/decision_staleness.py` — the Age-of-Information
  conversion for RQ4. Note the win-probability proxy is calibrated (ECE 0.054) but weak (skill
  +0.026 over a goal-difference lookup); if RQ4 is to carry weight, improve or replace it.
- `scripts/characterize_feed.py`, `scripts/kickoff_concurrency.py` — event-rate and concurrency
  characterisation, for RQ3's congestion analysis.
- `tests/unit/test_manuscript_consistency.py` — the pattern for pinning manuscript numbers to
  their source CSVs. Reproduce this for the new paper.

## Deliverables

1. A collection harness (poller + storage + provenance), tested to the standard above.
2. A committed raw-capture dataset with per-poll timestamps, plus derived per-event timings.
3. Analysis scripts producing every figure and table from committed data.
4. A JSA-format manuscript. Keep the language plain: short sentences, systems terms explained.
5. A consistency test suite that fails if the manuscript and the data disagree.

## What success looks like

A JSA reader learns how stale their live feed actually is, how much providers differ, and how
long they hold a wrong in-play estimate as a result. That is a sports-analytics finding. The
companion systems paper becomes this paper's methods citation.

## What would make this fail

Collecting first and designing after. Leading with the assumption-laden absolute number instead
of the robust cross-provider differential. Polling too slowly to resolve the effect. Using a
provider whose ToS forbids it. Any of these sinks the paper — check all four before writing
code.
