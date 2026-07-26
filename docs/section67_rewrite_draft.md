# §6.7 rewrite — working draft

**Status: draft. Not applied to `paper.tex`.** Numbers for the 88% and 95% levels and the whole
message-size sweep are still landing; every figure below marked `[PENDING]` is a placeholder and
must be replaced from the committed CSV before this goes near the manuscript. Nothing here is to
be quoted until this header is removed.

## What changes and what does not

The source audit — currently §6.7 up to and including the paragraph at l. 1125–1130 — **does not
change at all.** It never depended on the run. Specifically these survive verbatim:

- end-to-end latency is a cross-process, and in a distributed deployment cross-host, timestamp
  difference, at the named commit, file and line;
- `if (endToEndLatencyMicros > 0)` admits only positive samples, and nothing counts the drops;
- the reported distribution is therefore conditioned on being positive, so a causality violation
  cannot appear in the output even in principle;
- the retention rate is not merely unpublished but unrecoverable from a completed run;
- the arithmetic consequence at the fast end (l. 1125–1130), which this rewrite promotes from a
  predicted consequence to a measured one.

What changes is the paragraph beginning *"We then ran it, and it discarded six thousand
samples"* (l. 1132) through *"...cannot report its own failure"* (l. 1169), and the four sites
that inherit its inference: abstract l. 70, contributions l. 202, limitations l. 2525,
conclusion l. 2631.

## Replacement prose

> **We then ran it, and it discarded almost everything.** A source audit is not a measurement, so
> we made the discards observable and ran the benchmark. The obvious experiment is impossible ---
> the violations never reach the output, because the guard removes them inside the harness --- so
> we added counters in the existing guard's `else` branch and changed nothing else: not the
> latency computation, not the guard's condition, not any reported statistic. The patch is in the
> artefact.
>
> An earlier version of this section reported a single such run, at $88\%$ background load, in
> which the benchmark discarded $6{,}000$ samples, and read that as the same causality violation
> we report in Section~\ref{sec:gate}. That reading was wrong, and the counter that produced it
> could not have distinguished the two: it was one total with no sign. Both a causality violation
> and a sub-millisecond delivery fail `> 0`, and they were counted together.
>
> We therefore split the counter --- zero, negative, most-negative, kept --- and swept background
> load from idle to $95\%$, three replicates per level, three minutes per cell.
>
> [TABLE: load level x kept / zero / negative, five levels]
>
> **In roughly [PENDING]$\,$000 discarded samples there was not one negative.** The most negative
> end-to-end latency observed at any load was $0$~$\mu$s. And the discarded share falls as the
> machine gets busier: at idle the benchmark discarded $98.49\%$ of its samples, at $75\%$ load
> $4.41\%$. Our own mechanism predicts the opposite direction --- Section~\ref{sec:twostate}
> establishes that inversions track scheduling stalls, which become *more* frequent under load,
> not less. A discard population that thins out as the machine fills up is not our failure mode.
>
> It is the arithmetic one, and it is the consequence described three paragraphs above. Kafka's
> `CreateTime` timestamp has millisecond resolution, so on a path whose true latency is a
> fraction of a millisecond most samples compute to exactly zero, fail the `> 0` guard, and
> disappear. Loading the machine lengthens the path past one tick, and the samples reappear. That
> is why the zero share falls with load, and it is why it falls back again when [message-size
> result PENDING].
>
> The benchmark's own output corroborates this without any instrumentation from us. Across eight
> runs it reports $32$ percentile values --- p50, p95, p99 and max --- and **every one of them is
> a whole number of milliseconds.** The only fractional statistics it reports are the averages,
> which is the one column that could be fractional, being a mean of integers. Three runs report
> p50 = p95 = p99 = max = $1.0$. That is not a narrow latency distribution. It is a distribution
> with a single value in it, printed to three decimal places.
>
> **The refutation was in our own artefact.** We should say where this evidence was, because it
> was not anywhere new. The counter we added printed one line per thousand discards, and each
> line carried the sample that triggered it. All eleven lines committed with the original run
> read `sample_micros=0`. Beside them, the benchmark's own progress output reported a median
> publish latency of $0.4$--$0.5$~ms --- sub-millisecond, which is exactly the condition under
> which a millisecond-resolution timestamp difference collapses to zero. The number that refutes
> the causality reading, and the mechanism that explains it, were both in the artefact from the
> day we committed it. What we lacked was not data but a reason to look at the sign, and the
> total we had chosen to report did not have one. We record this because it is the same failure
> the paper is about, one level up: a summary statistic that concealed the distinction that
> mattered, in an instrument we built ourselves to detect exactly that.
>
> **What this costs us, and what it does not.** We withdraw the claim that the OpenMessaging
> Benchmark was observed discarding causality violations. We did not observe that. What we
> observed is worse for the benchmark and weaker for us, and both halves of that sentence should
> be stated plainly. At idle, this benchmark computed its reported latency distribution from
> $1.51\%$ of the samples it took, discarded the other $98.49\%$ without counting them, and
> printed a throughput and latency summary that looks entirely healthy. A reader of that output
> cannot tell. Neither could we, until we patched it.
>
> The audit above stands unchanged, because it never rested on this run. The guard is real, it is
> uncounted, and the distribution it produces is conditioned on the violation not having
> occurred. What we can no longer say is that we have seen the violation happen in software we
> did not write. The exposure is demonstrated by construction; the occurrence is not.

## Why this is the better section

Three reasons, worth being explicit about since the change was forced rather than chosen.

1. It is the paper's own thesis, applied to the paper. §6.5 argues that instruments conceal
   their own failures and that a healthy-looking summary is not evidence of a healthy
   measurement. A benchmark reporting a confident latency distribution computed from 1.5% of its
   data is a cleaner instance of that than a discard count ever was.
2. It is harder to dismiss. "Six thousand samples in one three-minute run" invites the response
   that one run proves little --- which is exactly what referee M3 said. Fifteen cells across
   five load levels, with a mechanism that predicts the direction of the trend and a second sweep
   that moves it deliberately, does not.
3. The withdrawal is itself evidence for the method. We built a gate, pointed it at our own
   headline external result, and it failed the result. A paper arguing for routine integrity
   audits is in a poor position to report only the audits that came out well --- and this is the
   second claim we have withdrawn this way, after the M/G/1 form.

## Sites to update together

| site | line | current | change |
|---|---|---|---|
| abstract | 70 | "silently discarded $6{,}000$ end-to-end samples, about $6.7\%$" | the resolution finding: reported a distribution from a small fraction of its samples |
| contributions | 202 | "It discarded $6{,}000$ end-to-end samples in three minutes" | same, plus the sweep |
| related work | 243 | "its runs it discarded on integrity grounds" | check wording survives |
| limitations | 2525 | "discarded $6{,}000$ samples under load ... establishes the failure outside our own harness" | **must change**: it no longer establishes that |
| conclusion | 2631 | "Under load it dropped $6{,}000$ end-to-end samples" | the resolution finding |
| §7 requirements | 2332–2342 | retention-rate recommendation | unaffected, and strengthened |
| `docs/laws.md` | 241–242 | "discarded **6,000** ... The exposure is not ours alone" | **must change**, incl. the heading |
| `docs/referee_response_plan.md` | 236 | status board: M1 empirical closure **CLOSED** | reopen, then close on the new finding |
| `external/omb/README.md` | 4 | "about 6.7% of a three-minute run" | rewrite to the resolution finding |
| `external/omb/omb_discard_evidence.txt` | 12 | raw counter output | **keep exactly as is** — it is the primary record, and it is what refutes the claim |

`README.md` and `reproducibility/README.md` are clean — the claim did not propagate there.

The `omb_discard_evidence.txt` row matters: the instinct is to regenerate it alongside the
rewrite, and that would be wrong. Every line in it reads `sample_micros=0`. It is the evidence
against the claim it was committed to support, and it should stay byte-for-byte so a reader can
verify the withdrawal from the original artefact rather than from a file we touched afterwards.

The limitations entry is the one to be most careful with. It currently uses the OMB run to argue
the failure is not ours alone. After this change the source audit carries that claim and the run
does not, so the sentence has to be rebuilt rather than edited.
