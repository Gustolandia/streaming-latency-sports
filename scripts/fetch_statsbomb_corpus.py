#!/usr/bin/env python3
"""
fetch_statsbomb_corpus.py
Fetch the StatsBomb open-data corpus for a season range, from a pinned commit.

Why this replaces fetch_statsbomb_events.sh: that script fetched a single hard-coded
competition-season (1. Bundesliga 2023/24, 34 matches). The study claimed a 34-match corpus but
only 11 replay plans were ever generated, and concurrency levels above N=10 silently re-used
them. Characterising what a football event feed actually demands needs the whole modern corpus,
across competitions, eras and both genders.

Everything is keyed to a pinned open-data commit, so the corpus is reconstructible exactly.
Raw JSON is intentionally *not* committed (it is gigabytes); replay plans derived from it are.

CLI:
    python scripts/fetch_statsbomb_corpus.py --dry-run          # size it first
    python scripts/fetch_statsbomb_corpus.py --out data/raw/statsbomb
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

PINNED_SHA = "3bfbffe1de5750ebd47d770be0bb924a10cde54f"
BASE = "https://raw.githubusercontent.com/statsbomb/open-data/{sha}/data"


def season_start_year(season_name):
    """Leading year of a season label: '2015/2016' -> 2015, '2022' -> 2022, junk -> None."""
    m = re.match(r"^(\d{4})", str(season_name))
    return int(m.group(1)) if m else None


def select_seasons(competitions, year_from, year_to):
    """Competition-seasons whose season *starts* within [year_from, year_to].

    Deduplicated and ordered, because competitions.json contains one record per
    competition-season-gender and some repeat.
    """
    out = []
    for e in competitions:
        y = season_start_year(e.get("season_name"))
        if y is None or not (year_from <= y <= year_to):
            continue
        out.append({
            "competition_id": e["competition_id"],
            "season_id": e["season_id"],
            "competition_name": e.get("competition_name"),
            "season_name": e.get("season_name"),
            "gender": e.get("competition_gender"),
            "country": e.get("country_name"),
            "season_start_year": y,
        })
    seen, uniq = set(), []
    for r in out:
        key = (r["competition_id"], r["season_id"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return sorted(uniq, key=lambda r: (r["competition_id"], r["season_id"]))


def competitions_url(sha):
    return f"{BASE.format(sha=sha)}/competitions.json"


def matches_url(sha, competition_id, season_id):
    return f"{BASE.format(sha=sha)}/matches/{competition_id}/{season_id}.json"


def events_url(sha, match_id):
    return f"{BASE.format(sha=sha)}/events/{match_id}.json"


def _default_get(url, timeout=60):  # pragma: no cover - network, injected in tests
    import requests
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.content


def fetch_json(url, getter=None):
    """Fetch and parse JSON; returns None on any transport or parse failure."""
    getter = getter or _default_get
    try:
        return json.loads(getter(url).decode("utf-8"))
    except Exception:      # noqa: BLE001 - any failure means "skip this item"
        return None


def save_events(match_id, dest_dir, sha, getter=None, force=False):
    """Write one match's events. Returns 'cached' | 'ok' | 'fail'.

    Resumable by design: a non-empty existing file is trusted unless --force, so an
    interrupted multi-thousand-match fetch can simply be re-run.
    """
    dest = Path(dest_dir) / f"{match_id}.json"
    if dest.exists() and dest.stat().st_size > 0 and not force:
        return "cached"
    payload = fetch_json(events_url(sha, match_id), getter)
    if payload is None:
        return "fail"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload), encoding="utf-8")
    return "ok"


def collect_matches(seasons, sha, getter=None):
    """Match records for every selected season, each tagged with its competition metadata."""
    matches = []
    for s in seasons:
        payload = fetch_json(matches_url(sha, s["competition_id"], s["season_id"]), getter)
        if not payload:
            continue
        for m in payload:
            matches.append({
                "match_id": m.get("match_id"),
                "match_date": m.get("match_date"),
                "kick_off": m.get("kick_off"),
                "competition_id": s["competition_id"],
                "season_id": s["season_id"],
                "competition_name": s["competition_name"],
                "season_name": s["season_name"],
                "gender": s["gender"],
                "season_start_year": s["season_start_year"],
                "home_team": (m.get("home_team") or {}).get("home_team_name"),
                "away_team": (m.get("away_team") or {}).get("away_team_name"),
                "home_score": m.get("home_score"),
                "away_score": m.get("away_score"),
                "competition_stage": (m.get("competition_stage") or {}).get("name"),
            })
    return matches


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fetch a StatsBomb open-data corpus slice")
    ap.add_argument("--sha", default=PINNED_SHA, help="pinned open-data commit")
    ap.add_argument("--from-year", type=int, default=2003)
    ap.add_argument("--to-year", type=int, default=2023)
    ap.add_argument("--out", default="data/raw/statsbomb")
    ap.add_argument("--index-out", default="data/processed/corpus_index.csv",
                    help="match-level index (kick_off times drive the concurrency analysis)")
    ap.add_argument("--dry-run", action="store_true",
                    help="resolve seasons and matches, write the index, fetch no events")
    ap.add_argument("--max-matches", type=int, default=0, help="0 = no limit")
    ap.add_argument("--force", action="store_true", help="re-fetch events already on disk")
    ap.add_argument("--sleep", type=float, default=0.0, help="delay between event fetches")
    args = ap.parse_args(argv)

    comps = fetch_json(competitions_url(args.sha))
    if not comps:
        print("Could not fetch competitions.json")
        return 1
    seasons = select_seasons(comps, args.from_year, args.to_year)
    print(f"{len(seasons)} competition-seasons in {args.from_year}-{args.to_year} "
          f"({len({s['competition_name'] for s in seasons})} competitions)")

    matches = collect_matches(seasons, args.sha)
    if args.max_matches:
        matches = matches[:args.max_matches]
    print(f"{len(matches)} matches")

    idx = Path(args.index_out)
    idx.parent.mkdir(parents=True, exist_ok=True)
    import csv
    with idx.open("w", newline="", encoding="utf-8") as f:
        if matches:
            w = csv.DictWriter(f, fieldnames=list(matches[0].keys()))
            w.writeheader()
            w.writerows(matches)
    print(f"Wrote match index -> {idx}")

    if args.dry_run:
        print("dry run: no event files fetched")
        return 0

    dest = Path(args.out) / args.sha / "events"
    tally = {"ok": 0, "cached": 0, "fail": 0}
    for i, m in enumerate(matches, 1):
        tally[save_events(m["match_id"], dest, args.sha, force=args.force)] += 1
        if args.sleep:
            time.sleep(args.sleep)
        if i % 100 == 0:
            print(f"  {i}/{len(matches)} ok={tally['ok']} cached={tally['cached']} "
                  f"fail={tally['fail']}")
    print(f"events -> {dest}: ok={tally['ok']} cached={tally['cached']} fail={tally['fail']}")
    return 1 if tally["fail"] and not tally["ok"] and not tally["cached"] else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
