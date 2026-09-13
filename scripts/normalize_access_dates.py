#!/usr/bin/env python3
"""
normalize_access_dates.py
One form for the date an online source was read: IEEE's "Accessed: Mon. D, YYYY."

Round 79 (W6). The bibliography dated its online sources four ways -- "Read 2026-08-21",
"accessed 19 August 2026", "Accessed: June 15, 2026" and, for three entries, no date at all.
Round 71 was right that the dates belong in the entries; the referee asked only that one form
be used, and the journal's own recent papers use IEEE's (a TC 2025 reference reads "Accessed:
Feb. 17, 2024."). This rewrites every dated note into that form, deterministically, and the
suite fails if any of the old forms returns (tests/unit/test_round79_findings.py).

It changes only the date phrase. A date is never invented here: an entry with no date is left
alone. Of the three article references that lacked one, one was re-read and dated by hand; the
other two stay undated because dating them grew the reference column by a line each, and the
referee's condition was that the form must not cost the page budget.

CLI:
    python scripts/normalize_access_dates.py manuscript_references.bib [--check]
"""
import argparse
import re
import sys

#: IEEE's month abbreviations, as IEEEtran renders them in this bibliography ("Sep. 2006").
MONTHS = ("Jan.", "Feb.", "Mar.", "Apr.", "May", "Jun.",
          "Jul.", "Aug.", "Sep.", "Oct.", "Nov.", "Dec.")
FULL = ("January", "February", "March", "April", "May", "June", "July", "August",
        "September", "October", "November", "December")

# Whitespace between the words is any whitespace, a line break included: the first run of this
# script matched "Read 2026-08-21" and missed three entries whose note wrapped as "Read" /
# "2026-09-10", and the rendered supplement still carried them.
ISO_READ = re.compile(r"Read\s+(\d{4})-(\d{2})-(\d{2})")
DAY_MONTH_YEAR = re.compile(r"(;\s*|\.\s*|^)[Aa]ccessed\s+(\d{1,2})\s+(%s)\s+(\d{4})"
                            % "|".join(FULL), re.M)
# Without May: it is its own abbreviation, so "Accessed: May 5, 2026" is already IEEE's form, and
# counting it as a retired one made the check fail on a correct date (found by the unit test).
MONTH_DAY_YEAR = re.compile(r"Accessed:\s+(%s)\s+(\d{1,2}),\s+(\d{4})"
                            % "|".join(m for m in FULL if m != "May"))

#: Every form this script retires. The test holds the bibliography to none of them.
OLD_FORMS = (ISO_READ, re.compile(r"[Aa]ccessed\s+\d{1,2}\s+(%s)\s+\d{4}" % "|".join(FULL)),
             MONTH_DAY_YEAR)


def ieee(year, month, day):
    return "Accessed: %s %d, %s" % (MONTHS[int(month) - 1], int(day), year)


def normalize(text):
    """Return (text, n) with every dated note in IEEE's form and the number of rewrites."""
    n = 0

    def iso(m):
        nonlocal n
        n += 1
        return ieee(m.group(1), m.group(2), m.group(3))

    def dmy(m):
        nonlocal n
        n += 1
        lead = m.group(1)
        # "; accessed 19 August 2026" was a clause; the IEEE form is its own sentence.
        lead = ". " if lead.strip().startswith(";") else lead
        return lead + ieee(m.group(4), FULL.index(m.group(3)) + 1, m.group(2))

    def mdy(m):
        nonlocal n
        n += 1
        return ieee(m.group(3), FULL.index(m.group(1)) + 1, m.group(2))

    text = ISO_READ.sub(iso, text)
    text = DAY_MONTH_YEAR.sub(dmy, text)
    text = MONTH_DAY_YEAR.sub(mdy, text)
    return text, n


def old_forms(text):
    """Every retired date form still present, as (line number, matched text)."""
    # Over the whole text, not line by line, so a form broken across a line is still found.
    found = []
    for pat in OLD_FORMS:
        for m in pat.finditer(text):
            found.append((m.start(), text.count("\n", 0, m.start()) + 1,
                          " ".join(m.group(0).split())))
    return [(line, match) for _, line, match in sorted(found)]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Normalize access dates to IEEE's form")
    ap.add_argument("bib")
    ap.add_argument("--check", action="store_true",
                    help="report retired forms and exit non-zero if any remain; write nothing")
    args = ap.parse_args(argv)
    with open(args.bib, encoding="utf-8") as fh:
        text = fh.read()
    if args.check:
        hits = old_forms(text)
        for line, found in hits:
            print("%s:%d: %s" % (args.bib, line, found))
        return 1 if hits else 0
    new, n = normalize(text)
    if new != text:
        with open(args.bib, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(new)
    print("rewrote %d date(s)" % n)
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
