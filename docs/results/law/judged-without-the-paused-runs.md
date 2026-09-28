# Judged without the runs a pause held: every prediction again, as a check after the fact

**28 September 2026, on every run the three pairs made, less the 222 a pause held.** A *pause* is a
message more than 150 ms late past the warm-up, as the quality report and
[`pause_census.py`](../../../scripts/pause_census.py) count them. On the two x86 pairs they came
from the driver's disk stalling the receiving program, or from the Kafka broker failing to reach
its own controller, and on the Arm pair once
([the strange results, read](the-strange-results-read-28-sep.md)). Nothing in the plan leaves such
runs out: the integrity rule counted them, and every verdict of plan version 32 stands as judged on
[all the runs](judged-with-and-without-the-brake.md). This reading asks whether any verdict rests
on them. It was decided after the verdicts were known, so it is a check on them and not a verdict.

**Words used here.** A *verdict* is a prediction's answer by its frozen rule. A *view* is the
collected campaigns laid out again with some runs left out, every file a link to the collected
one, so that each frozen judge reads it unchanged. The view here is laid out by the `without`
command of [`brake_views.py`](../../../scripts/brake_views.py), from the list of runs
`pause_census.py` wrote, and every judge is run as the final judging ran it. The answers are in
[`judged-27-sep/unpaused/`](judged-27-sep/unpaused/), and what the view left out, run by run, in
[`judged-27-sep/views/unpaused.json`](judged-27-sep/views/unpaused.json).

## What was left out

*Plain words:* about one run in forty on each x86 pair, and one run on Arm.

**222 runs**: 112 on the first x86 pair, 109 on the second and 1 on the Arm pair, leaving 7,880
runs in the 156 campaigns. The runs left out are the ones the pause census marks paused: a
message in them arrived more than 150 ms late after the warm-up.

## One verdict changes, and it sits on the edge of its rule

*Plain words:* every prediction gives the same answer as before except P3a on the first x86 pair,
where the answer turns on the last hundredth of a millisecond of an interval.

| Prediction | Block, pair | All runs | Without the 222 paused runs |
|---|---|---|---|
| P1 | A1, first x86 | not confirmed | not confirmed |
| P2, P2b, P2d | A2, both backends | not confirmed | not confirmed |
| P2c | A2, Kafka / Redis | not confirmed / confirmed | the same |
| P3a | A3, first x86 (19 September) | not confirmed | **confirmed** |
| P3a | A3, the four other campaigns | not confirmed | not confirmed |
| P3b | A3, five campaigns | confirmed | confirmed |
| P4 | A7, first x86 | not confirmed | not confirmed |
| P6 | A6's recordings | not confirmed | not confirmed |
| P7 | A5, second x86 | not confirmed | not confirmed |
| P8 | A8, both x86 and Arm | not confirmed | not confirmed |
| P9 | A4, Arm | not confirmed | not confirmed |
| A9-1, A9-2, A9-2b | A9, all three pairs | not confirmed | not confirmed |

**P3a on the first x86 pair.** P3a asks that the cliff's halfway point move by less than 0.25 ms
either way between the lowest and the highest load whose plateau is at least 2%, with its whole
95% interval inside that band, on both readings. On all 288 runs of that campaign the fitted
reading's interval runs from **−0.2526 to 0.2341 ms**, its lower end 0.0026 ms past the band, and
P3a is not confirmed. Without its 6 paused runs it runs from **−0.2463 to 0.2272 ms**, inside, and
P3a is confirmed. The free reading holds both ways (−0.1027 to 0.1779, then −0.1376 to 0.1781). An
interval end 0.0026 ms past the bar on one side and 0.0037 ms inside it on the other is not a
finding either way: the verdict on all the runs stands, and it is recorded here as resting on its
rule's edge.

## What moved

*Plain words:* the numbers the verdicts rest on moved little; the most was P8 on x86.

- **P1, Kafka:** the slope of the cliff on the slice, 0.758 free and 0.230 fitted, becomes 0.749 and
  0.222. On Redis 1.007 and 0.662 become 1.006 and 0.667.
- **P8, x86:** Python's plateau over Java's, 3.25 (2.79 to 3.91), becomes 3.50 (2.88 to 4.51),
  against the 1.5 P8 allows.
- **A9-2b:** the same four of six parts meet its rule. On the first x86 pair's Kafka part 21 of 27
  setups are within the band, where 22 of 28 were, and its median ratio moves from 1.18 to 1.19.
- **P3a, second x86 pair:** the free reading's move of the halfway point, −0.188 ms, becomes −0.275
  ms; its interval already reached past the band, and still does.

## How this was read

The view was laid out with

```
python scripts/brake_views.py without --campaigns runs/azure/final_campaigns --out runs/azure/brake_views --view unpaused --runs-csv docs/results/law/strange-results-28-sep/pause_runs.csv
```

and every judge run on it with the options of the final judging (`scripts/judge_campaigns.py`, and
`helper_waits.py` and `m0_read.py` as there). The folders in the answers are named
`campaigns/<pair>/<campaign>`, as in the other views.

## Pocket dictionary

- **Pause**: a message more than 150 ms late after the warm-up.
- **Paused run**: a run with at least one pause.
- **P3a**: load does not move the cliff; the halfway point moves by less than 0.25 ms either way.
- **Free reading / fitted shape**: a curve required only never to rise, and a plateau, straight
  fall and floor; a prediction passes only where both agree.
- **Verdict**: a prediction's answer by its frozen rule.
- **View**: the campaigns laid out again with some runs left out, for a judge to read unchanged.
