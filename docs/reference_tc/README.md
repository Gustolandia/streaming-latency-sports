# Two IEEE Transactions on Computers papers, kept for reference

Downloaded 2026-08-25 to settle questions of house norm rather than house *rule*. The rules
are in the Author Information page and are already gated in the test suite; these answer the
different question of what accepted TC papers actually look like.

Both are author preprints of accepted TC papers, chosen because they are the closest in kind
to ours that are retrievable in full: software-systems work with heavy experimental
evaluation, rather than the circuit and accelerator papers that dominate TC's arXiv presence.

| | `scavenger_plus_TC.pdf` | `axi_realm_TC.pdf` |
|---|---|---|
| Title | Scavenger+: Revisiting Space-Time Tradeoffs in Key-Value Separated LSM-trees | AXI-REALM: Safe, Modular and Lightweight Traffic Monitoring and Regulation |
| arXiv | 2508.13935 | 2501.10161 |
| Status | Accepted by IEEE Transactions on Computers | Accepted as a **regular paper** in IEEE Transactions on Computers |
| Pages | **14** | **14** |
| References | **45** | 36 |
| Figures | **17** | **13** |
| Tables | 1 | 3 |
| Sections | I Intro, II Preliminaries, III Design, IV Evaluation, V Related Work, VI Conclusion | I Intro, II Background, III Architecture, …, VI Related Work, VII Conclusion |

## What they settle

**Page length.** Both are 14 pages. TC allows 10–12 before mandatory overlength page charges
and 14 as the hard maximum, so both are paying MOPC for two pages. Our 12-page target is
therefore *stricter than the venue norm*, not looser — a deliberate choice rather than a
constraint, and one worth re-examining whenever holding 12 starts costing content.

**Reference count.** Scavenger+ carries exactly 45, the cap. Sitting at the cap, as we do, is
normal and not a sign of padding.

**Figure count.** This is the sharpest difference. TC publishes *no* limit on figures; the
observed norm among these two is **13 and 17**. Our main text carries **7**. We are at roughly
half the peer norm, and the binding constraint is the self-imposed 12-page target rather than
anything the journal says. The standing instruction to sit at "75% of the image limit" has no
published limit to work from; against the observed norm of ~15 it would imply about 11.

**Related work placement.** Both put Related Work second-to-last, immediately before the
conclusion. Ours is Section II. Both arrangements are common at TC and no referee round has
raised it; recorded here only so the difference is a known choice rather than an oversight.

## What they do not settle

Neither is a measurement-validity paper, and neither audits an instrument. TC's published
scope covers this work explicitly — "operating systems, software systems", "specification,
design, prototyping, and testing methods and tools", and "case studies and experimental and
theoretical evaluations" — but no comparable paper in the arXiv-visible sample argues from
the same position, so these two are useful for form and not for content.
