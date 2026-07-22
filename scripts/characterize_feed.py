#!/usr/bin/env python3
"""
characterize_feed.py
Measure what a live football event feed actually demands of a streaming pipeline.

Every latency budget quoted for football analytics is asserted rather than derived, and every
concurrency axis this project benchmarked was invented. Before asking whether infrastructure
can keep up, the workload itself has to be described: how fast do events arrive, how bursty are
they, and does that differ by competition, era or gender?

Per match we compute:
  * event count and match wall duration (from the last event's clock)
  * mean arrival rate, and the peak rate over a sliding window (the burst that actually sizes
    a buffer -- a mean of 0.4 events/s conceals bursts many times higher)
  * inter-arrival percentiles, including the short tail that a per-message round trip pays for

StatsBomb timestamps are match-clock, not wall-clock, and stoppages are not represented, so
these are *feed* rates under the standard convention that events are emitted as they occur.

CLI:
    python scripts/characterize_feed.py --events-dir data/raw/statsbomb/<sha>/events \
        --index data/processed/corpus_index.csv --out docs/results/football/feed
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_BURST_WINDOW_S = 10.0


def event_times(events):
    """Absolute seconds from kick-off for each event, ordered.

    `minute`/`second` are per-period match clock, so periods must be offset or the second half
    would overlap the first. Period lengths are taken from the data rather than assumed, which
    keeps extra time and stoppage correct.
    """
    rows = []
    for e in events:
        p = e.get("period")
        m, s = e.get("minute"), e.get("second")
        if p is None or m is None or s is None:
            continue
        rows.append((int(p), float(m) * 60.0 + float(s)))
    if not rows:
        return np.array([])
    rows.sort()
    # Offset each period by the greatest clock reached in all earlier periods.
    per_max, offset, out = {}, {}, []
    for p, t in rows:
        per_max[p] = max(per_max.get(p, 0.0), t)
    running = 0.0
    for p in sorted(per_max):
        offset[p] = running
        running += per_max[p]
    for p, t in rows:
        out.append(offset[p] + t)
    return np.array(sorted(out))


def peak_rate(times, window_s=DEFAULT_BURST_WINDOW_S):
    """Highest events-per-second over any sliding window of `window_s`.

    This is the number that sizes a buffer. A two-pointer sweep over the sorted times is exact
    and linear, so it can run over thousands of matches.
    """
    if times is None or len(times) == 0 or window_s <= 0:
        return 0.0
    best, lo = 0, 0
    for hi in range(len(times)):
        while times[hi] - times[lo] > window_s:
            lo += 1
        best = max(best, hi - lo + 1)
    return best / float(window_s)


def match_profile(events, window_s=DEFAULT_BURST_WINDOW_S):
    """Rate and burst profile for one match; None if the match has too few usable events."""
    t = event_times(events)
    if len(t) < 2:
        return None
    duration = float(t[-1] - t[0])
    if duration <= 0:
        return None
    gaps = np.diff(t)
    nz = gaps[gaps > 0]
    return {
        "n_events": int(len(t)),
        "duration_s": duration,
        "mean_rate_evs": len(t) / duration,
        "peak_rate_evs": peak_rate(t, window_s),
        "gap_p50_s": float(np.median(gaps)),
        "gap_p05_s": float(np.percentile(gaps, 5)),
        "gap_min_s": float(nz.min()) if len(nz) else 0.0,
        "burstiness": (peak_rate(t, window_s) / (len(t) / duration)) if duration else 0.0,
    }


def load_match(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def profile_corpus(events_dir, index_df=None, window_s=DEFAULT_BURST_WINDOW_S, limit=0):
    """Profile every match file, joined to competition metadata where available."""
    meta = {}
    if index_df is not None and "match_id" in index_df.columns:
        for r in index_df.to_dict("records"):
            meta[str(r["match_id"])] = r
    rows = []
    files = sorted(Path(events_dir).glob("*.json"))
    if limit:
        files = files[:limit]
    for fp in files:
        events = load_match(fp)
        if not events:
            continue
        prof = match_profile(events, window_s)
        if prof is None:
            continue
        mid = fp.stem
        m = meta.get(mid, {})
        prof.update({
            "match_id": mid,
            "competition_name": m.get("competition_name"),
            "season_name": m.get("season_name"),
            "gender": m.get("gender"),
            "season_start_year": m.get("season_start_year"),
        })
        rows.append(prof)
    return pd.DataFrame(rows)


def summarize(df, by=None):
    """Median profile overall or grouped, so a single competition cannot skew the picture."""
    if df is None or df.empty:
        return pd.DataFrame()
    cols = ["n_events", "duration_s", "mean_rate_evs", "peak_rate_evs",
            "gap_p50_s", "gap_p05_s", "burstiness"]
    present = [c for c in cols if c in df.columns]
    if by and by in df.columns:
        g = df.groupby(by)[present].median().reset_index()
        g["n_matches"] = df.groupby(by).size().values
        return g.sort_values("n_matches", ascending=False)
    out = df[present].median().to_frame().T
    out["n_matches"] = len(df)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Characterise football event feeds")
    ap.add_argument("--events-dir", required=True)
    ap.add_argument("--index", default="data/processed/corpus_index.csv")
    ap.add_argument("--out", default="docs/results/football/feed")
    ap.add_argument("--burst-window", type=float, default=DEFAULT_BURST_WINDOW_S)
    ap.add_argument("--limit", type=int, default=0, help="0 = all matches")
    args = ap.parse_args(argv)

    idx = None
    try:
        idx = pd.read_csv(args.index)
    except (OSError, ValueError):
        print(f"(no match index at {args.index}; profiling without competition metadata)")

    df = profile_corpus(args.events_dir, idx, args.burst_window, args.limit)
    if df.empty:
        print(f"No usable matches under {args.events_dir}")
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "match_profiles.csv", index=False)
    overall = summarize(df)
    overall.to_csv(out / "feed_summary.csv", index=False)
    for key, name in (("competition_name", "by_competition"), ("gender", "by_gender"),
                      ("season_start_year", "by_year")):
        s = summarize(df, key)
        if not s.empty:
            s.to_csv(out / f"feed_{name}.csv", index=False)

    print(f"== feed characterisation over {len(df)} matches "
          f"(burst window {args.burst_window:g}s) ==")
    print(overall.to_string(index=False))
    bc = summarize(df, "competition_name")
    if not bc.empty:
        print("\nby competition (median):")
        print(bc.head(10).to_string(index=False))
    print(f"\nWrote results to {out}/")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
