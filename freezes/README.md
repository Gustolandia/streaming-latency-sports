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
