# Amendment 1: which of the products found are checked

Written 27 October 2026 at about 21:00 Irish time. The search under
[`AMENDMENT_01.md`](AMENDMENT_01.md) had run. No product it found beyond the seed list had been
checked.

**What happened.** The search found far more products than expected.
- Its three parts returned 1,483 rows.
- After duplicates, copies and the products that are plainly out, 411 new products looked like brokers
  on a first reading of their own descriptions. These are beyond the 23 brokers coded first and the
  seed list.
- Checking all 411 would have doubled the audit's work.

**The rule.** On the author's decision, a product the search found is checked only if it is
established:
- **An open-source project:** at least 1,000 stars on GitHub, a push on or after 27 October 2023, and
  not archived. A project on another code host is checked if it has at least 1,000 stars there, where
  the count can be read.
- **A commercial or cloud product:** checked if it has public documentation of what a consumer
  receives.
- **A standard:** always checked.

A product whose own page does not show which of these it is is screened first, by the same rule.

**What the rule left.**
- **To check or screen: 223 products.**
  - 37 open-source projects that meet the rule.
  - 8 standards.
  - 178 products known only by a product or project page, to be screened by the rule above.
- **Listed as found, not checked: 188 products.**
  - 107 open-source projects under 1,000 GitHub stars.
  - 1 project with no push since 27 October 2023.
  - 21 projects archived on GitHub.
  - 15 products archived or retired.
  - 44 projects on other code hosts. Of these, 8 have star counts that could be read, all under 1,000.
    For the other 36 the count could not be read.

Each product's reason goes into `candidates.json`.

**What it means for the findings.** The audit's statements about what brokers send cover three sets:
- the 23 brokers coded first;
- the seed list;
- the established products the search found.

A small project that was not checked might send a time that no checked broker sends. Wherever the
audit reports a finding, it says so.
