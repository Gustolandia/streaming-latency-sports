# Invalid: distributed OMB run of 2026-07-25 13:28Z

That run wrote `discarded_nonpositive=0`. **The zero is vacuous and must never be quoted.**

The benchmark never ran. The client worker on 10.0.1.122 failed to start with
`NoClassDefFoundError: com/beust/jcommander/ParameterException`, because the campaign rsync'd
OMB's built jars but not its Maven dependency tree under `~/.m2`, which `bin/benchmark-worker`
puts on the classpath. The coordinator aborted at 13:30:02Z with
`Connection refused: /10.0.1.122:8080` and produced no latency output at all — zero `Pub rate`
lines, zero `Aggregated` lines.

A harness that was never exercised discards nothing. Reporting this as "a second null under hard
conditions" would have been exactly the failure this paper is about: a number that looks like a
measurement and is an artefact of the instrument breaking.

The campaign now has three defences, and the first is the one that matters:

1. **Validate before writing.** The benchmark must have produced real latency output. If not, the
   result row is marked `valid=0` with a reason and carries no count.
2. **Verify both workers answer** before the benchmark starts, rather than discovering it after.
3. **Ship a self-contained distribution** (the packaged tarball), so the classpath cannot be
   half-present.

## Also invalid: `omb_discards.INVALID.csv` (embedded run, first attempt)

Reported `discarded_nonpositive=0`. **That zero is vacuous and reached a draft of the paper as a
genuine bounded negative.**

The run died about four seconds in with a `NullPointerException` in `FilePayloadReader.load`:
OMB reads its payload from a file, and `payloadFile` was absent from the workload YAML.
`messageSize` alone is honoured only by a path this configuration did not take. No latency was
ever measured — zero `Pub rate` lines — and the script wrote a count anyway, because a benchmark
that never runs discards nothing.

It was caught only because an output-validation gate written for the *distributed* variant made
the missing one here obvious. Superseded by `../omb_loaded_result.csv`, which records 6,000
discards under 88% load with `valid=1` and 24 `Pub rate` lines.
