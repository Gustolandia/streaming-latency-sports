# Freezes

A freeze is an experiment plan committed here before the experiments it describes are run. It
fixes, in advance, what we predict, how the runs are designed, how many there are, and the rule
that decides whether each prediction held. Researchers call this *pre-registration*.

## Why the plans are committed here

A prediction convinces a reader only if it was written down before the data. Every commit in
this public repository carries a date and an identifier, and neither can be changed later
without the change showing (a commit is a saved version of every file in the repository). So a
plan committed here shows what was predicted, and how it would be judged, before the first run
it covers.

## The rules

1. **A freeze is never edited.** A change is a new freeze in a new folder, numbered in order.
   Its first section lists what changed since the previous freeze and why, and says whether a
   result already seen prompted the change.
2. **Every file in a freeze has a fingerprint** in the folder's `SHA256SUMS` (a fingerprint is a
   64-character code computed from a file's bytes; changing one character changes the code), so
   a copy found anywhere can be checked against this one. Git stores these files byte for byte,
   so the fingerprints hold on every computer.
3. **Runs start after the commit is public.** No run a freeze covers starts before the freeze is
   on GitHub.
4. **Results are reported against the freeze in force when they ran**, and that includes every
   prediction that failed.

## The freezes

| Folder | Frozen | What it fixes |
|---|---|---|
| [`01-experiment-plan/`](01-experiment-plan/) | 16 September 2026 | the law campaign on Azure: its predictions, campaigns, repeats rule and analysis, and how its runs are checked, stopped and kept |
| [`02-experiment-plan/`](02-experiment-plan/) | 17 September 2026 | amends 01 after its first runs, which were stopped, and starts stage 0 again: the calibration known within 0.3 ms, the delay checked by the broker's own capture, the paper's Redis setting, M0 on bursty traffic, and runs protected from faults of the machines; prompted by results, as its first section says |
| [`03-experiment-plan/`](03-experiment-plan/) | 18 September 2026 | amends 02 after its first shakedown: every judgement about the added delay is read from the broker's own capture, where the delay is applied, and the paths are recorded by ping, TCP and UDP rather than judged, because ping is not the path the messages take |
| [`04-experiment-plan/`](04-experiment-plan/) | 18 September 2026 | amends 03 after stage 0 ran on all three pairs: a slice whose plateau lies below the client's own zero-delay trip is reported as out of reach and not run, and P1 and P9 are judged on the slices each pair can reach; the brake that stops a session on a got-it shift must clear that session's own zero-delay scatter, after a sound session was stopped by a brake set at 0.056 ms |
| [`05-experiment-plan/`](05-experiment-plan/) | 19 September 2026 | amends 04 after the rounds rule was run for A3 and no measured run was read: P3 asked two things at once and was confirmed only where both held, so its power was its weaker half's, and that half answered the same whether the law was true or false. It becomes P3a (load leaves the cliff where it is) and P3b (load raises the plateau), each with its own falsifier. P3a is judged by the whole interval of the movement rather than by the point estimate, which is how a claim that something did *not* change has to be made; A3 runs 16 rounds |
| [`06-experiment-plan/`](06-experiment-plan/) | 20 September 2026 | changes no rule and corrects how one was applied. Rounds are set at the spread a pair's pilot measured *for the backend the campaign runs*, as the plan has said since version 4; one figure pooled over both backends was used instead. Pooling assumes the two share a variance, and the pilots refute it — 0.213 for Kafka against 0.701 for Redis on the second x86 pair. What the departure cost is checked campaign by campaign and cost nothing: A1, A4 and A7 all clear the bar at their own backends' spreads |
| [`07-experiment-plan/`](07-experiment-plan/) | 20 September 2026 | settles what 06 left open: an A5 session measures its own baseline at its own core count, not only its own calibration. The baseline is the floor every trip is placed from and it moves with the core count for the same reasons the calibration does, so a two-CPU session would otherwise place its trips from a floor measured at eight |
| [`08-experiment-plan/`](08-experiment-plan/) | 20 September 2026 | fixes what each tool is predicted to do, before any tool campaign runs, from the documentation and source audit the plan asks for. Seven tools that carried a question mark are classified with the version each was read at, and each prediction's falsifiable content is stated. Records one earlier classification as **refuted** — RabbitMQ PerfTest does not keep negatives, it takes their size, so a clock offset is reported as delay — and records two of the audit's own eight search terms as weak, without changing them |

## Checking a freeze

In the freeze's folder, on Linux, macOS or Git Bash (the program recomputes every fingerprint
and compares it with the list; each file should report `OK`):

```bash
sha256sum -c SHA256SUMS
```

## Pocket dictionary

| Word | Plain meaning |
|---|---|
| Freeze | a plan committed here before its runs, and never edited afterwards |
| Pre-registration | the research practice of fixing predictions and analysis before the data exist |
| Commit | a saved, dated version of every file in the repository |
| Fingerprint (SHA-256) | a 64-character code computed from a file; any change to the file changes it |
| Amendment | a later freeze that changes an earlier one, with its reasons |
| Run | one measurement: a few minutes of messages through a broker |
