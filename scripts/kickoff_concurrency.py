#!/usr/bin/env python3
"""
kickoff_concurrency.py
Derive how many football matches are actually in play simultaneously, from real kick-off times.

Every concurrency level this project has benchmarked so far was chosen arbitrarily
(N in {1,5,10,20}, later {10,25,50,100}). That makes "does latency scale with concurrency?" a
question about an invented axis. Match metadata carries `match_date` and `kick_off`, so the
axis can instead be measured: a slot is a (date, kick-off time) at which several matches start
together, and overlap can be counted over a match's actual duration.

Two quantities are reported:

  * slot concurrency  -- matches sharing an exact kick-off instant. This is the classic
    "3 pm Saturday" structure and the final-matchday rule that forces simultaneous kick-offs.
  * overlap concurrency -- matches in play at the same instant given a nominal duration,
    which is what a streaming consumer actually sees.

IMPORTANT CAVEAT, and the analysis is designed to surface it rather than hide it: StatsBomb
open data is a *sample*, not a complete league record. Observed simultaneity is therefore a
LOWER BOUND on real-world concurrency. `league_matchday_bound()` supplies the structural upper
bound instead (a 20-team league plays 10 simultaneous matches on its final matchday).

CLI:
    python scripts/kickoff_concurrency.py --index data/processed/corpus_index.csv \
        --out docs/results/football/concurrency
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

# A football match occupies roughly two hours of wall clock: 2x45 min plus a 15 min interval
# plus stoppage. Used only for overlap counting, and exposed as a CLI knob.
DEFAULT_MATCH_MINUTES = 115.0


def parse_slots(df):
    """Add a `slot_ts` timestamp from match_date + kick_off; drop rows lacking either."""
    d = df.copy()
    d = d[d["match_date"].notna() & d["kick_off"].notna()]
    ts = pd.to_datetime(d["match_date"].astype(str).str.strip() + " "
                        + d["kick_off"].astype(str).str.strip(),
                        errors="coerce")
    d = d.assign(slot_ts=ts)
    return d[d["slot_ts"].notna()]


def slot_concurrency(df):
    """Matches per exact kick-off instant, with the competitions involved."""
    d = parse_slots(df)
    if d.empty:
        return pd.DataFrame(columns=["slot_ts", "n_matches", "competitions"])
    g = (d.groupby("slot_ts")
           .agg(n_matches=("match_id", "count"),
                competitions=("competition_name",
                              lambda s: ", ".join(sorted(set(map(str, s))))))
           .reset_index()
           .sort_values(["n_matches", "slot_ts"], ascending=[False, True]))
    return g


def overlap_concurrency(df, match_minutes=DEFAULT_MATCH_MINUTES):
    """Peak number of matches simultaneously in play, via a start/end sweep.

    Slot concurrency undercounts what a consumer sees: a 15:00 and a 16:00 kick-off overlap
    for most of an hour. Sweeping +1 at kick-off and -1 at kick-off+duration gives the true
    instantaneous count.
    """
    d = parse_slots(df)
    if d.empty:
        return pd.DataFrame(columns=["ts", "in_play"]), 0
    starts = d["slot_ts"].values.astype("datetime64[ns]")
    ends = starts + np.timedelta64(int(match_minutes * 60), "s")
    events = ([(t, 1) for t in starts] + [(t, -1) for t in ends])
    events.sort(key=lambda e: (e[0], -e[1]))
    ts, cur, series = [], 0, []
    for t, delta in events:
        cur += delta
        ts.append(t)
        series.append(cur)
    out = pd.DataFrame({"ts": ts, "in_play": series})
    return out, int(out["in_play"].max())


def league_matchday_bound(n_teams):
    """Structural upper bound: a league of n_teams plays n_teams/2 simultaneous matches.

    Domestic leagues schedule the final matchday simultaneously to protect competitive
    integrity, so this is a real operating condition rather than a hypothetical.
    """
    if n_teams is None or n_teams < 2:
        return 0
    return int(n_teams) // 2


def recommend_levels(slots, extra=None):
    """Concurrency levels a benchmark should test, derived from the observed distribution.

    Returns the median, upper-quartile and maximum observed slot occupancy, plus any
    structural bounds supplied, deduplicated and sorted. These become the N values the
    benchmark replays instead of round numbers.
    """
    if slots is None or slots.empty:
        base = []
    else:
        n = slots["n_matches"].values
        base = [int(np.median(n)), int(np.percentile(n, 75)), int(n.max())]
    levels = sorted({max(1, v) for v in base + list(extra or [])})
    return levels


def summarize(slots, peak_overlap, levels):
    return pd.DataFrame([{
        "n_slots": 0 if slots is None or slots.empty else int(len(slots)),
        "max_simultaneous_kickoffs": 0 if slots is None or slots.empty
                                     else int(slots["n_matches"].max()),
        "median_slot_occupancy": 0 if slots is None or slots.empty
                                 else float(np.median(slots["n_matches"])),
        "peak_matches_in_play": int(peak_overlap),
        "recommended_levels": ";".join(str(v) for v in levels),
    }])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Real concurrency from kick-off schedules")
    ap.add_argument("--index", default="data/processed/corpus_index.csv")
    ap.add_argument("--out", default="docs/results/football/concurrency")
    ap.add_argument("--match-minutes", type=float, default=DEFAULT_MATCH_MINUTES)
    ap.add_argument("--league-teams", type=int, action="append", default=None,
                    help="structural bound(s), e.g. --league-teams 20 --league-teams 18")
    args = ap.parse_args(argv)

    try:
        df = pd.read_csv(args.index)
    except (OSError, ValueError):
        print(f"Could not read {args.index}")
        return 1
    if "match_date" not in df.columns or "kick_off" not in df.columns:
        print(f"{args.index} lacks match_date/kick_off")
        return 1

    slots = slot_concurrency(df)
    overlap, peak = overlap_concurrency(df, args.match_minutes)
    bounds = [league_matchday_bound(t) for t in (args.league_teams or [])]
    levels = recommend_levels(slots, bounds)
    summary = summarize(slots, peak, levels)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    slots.to_csv(out / "kickoff_slots.csv", index=False)
    overlap.to_csv(out / "in_play_timeline.csv", index=False)
    summary.to_csv(out / "concurrency_summary.csv", index=False)

    print("== concurrency observed in the corpus ==")
    print(summary.to_string(index=False))
    if not slots.empty:
        print("\ntop simultaneous-kick-off slots:")
        print(slots.head(5).to_string(index=False))
    print("\nNOTE: StatsBomb open data is a sample, so observed simultaneity is a LOWER BOUND; "
          "--league-teams supplies the structural bound.")
    print(f"Wrote results to {out}/")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
