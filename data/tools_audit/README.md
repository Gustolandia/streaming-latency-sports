# T5: the documentation and issue audit

What each latency tool times, what it does with zero and negative values, whether it warns anyone,
and whether users ever reported it. The protocol is frozen in the experiment plan (freeze 04,
Section "Experiments for Mode 2"), and it is followed here exactly:

1. read the tool's documentation and source for three things -- which clock and resolution it times
   with, what it does with zero or negative values, and any warning about scheduling or clock
   effects;
2. search its issue tracker and mailing list with eight fixed terms: `negative latency`,
   `negative`, `clock skew`, `resolution`, `rounding`, `millisecond`, `nanosecond`, `latency 0`;
3. record every relevant report with its date and outcome: fixed, closed without a fix, or still
   open.

No machines are used. Nothing here reads a run of ours.

## How a record is to be read

Each file holds one batch of tools as they were audited. Every factual claim carries a URL or a
`path:line`, so a reader can check it without trusting the record.

`checked_here` is the part of each record that was read back against the tool's own source by the
author, line by line, rather than taken on the auditor's word. The rest is the auditor's reading
and is marked as such. A claim that could not be determined says so; it is not filled in with
something plausible.

## What the plan predicted

The plan's own table of tools (freeze 04, Section "The tools") classifies each tool's handling of
odd values *before* this audit ran, and the plan states that this classification is itself a
prediction. Where the audit disagrees with it, the disagreement is recorded as a failed prediction
and reported, not quietly corrected: `plan_said` and `audit_found` sit beside each other in the
record.
