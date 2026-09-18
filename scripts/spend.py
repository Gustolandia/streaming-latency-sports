#!/usr/bin/env python3
"""
spend.py -- what the testbed has cost, kept alongside the runs it paid for.

Azure bills a day late, so a figure read from the bill cannot say what a run cost while it was
running. This keeps a second figure that can: every look of the watch adds the machine time since
the last look, at the machine's own list price, to a ledger. The ledger is an estimate of what
has been spent, to the minute; `billed` reads what Azure has actually charged, which arrives
later, and the two are printed together so the estimate can be checked against the truth.

A gap in the ledger is counted at MAX_GAP_S, not for its whole length: when the watch is not
running, nobody knows whether the machines were, so the estimate stays honest by staying low and
saying so.

Every run's start is a point on the ledger's timeline, so `at` gives what had been spent when a
run began, and quality_report.py writes it beside the run.

CLI:
    python scripts/spend.py show [--ledger runs/azure_watch/spend.json]
    python scripts/spend.py billed [--since 2026-09-01]
"""
import argparse
import datetime
import json
import os
import subprocess
import sys

#: A look further than this from the last one counts as this much machine time, not its own gap.
MAX_GAP_S = 900.0
#: Where the watch keeps the ledger.
LEDGER = os.path.join("runs", "azure_watch", "spend.json")
STAMP = "%Y-%m-%dT%H:%M:%SZ"


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def when(text):
    return datetime.datetime.strptime(text, STAMP).replace(tzinfo=datetime.timezone.utc)


def load(path=LEDGER):
    """The ledger, or an empty one."""
    try:
        with open(path, encoding="utf-8") as fh:
            found = json.load(fh)
    except (OSError, ValueError):
        return {"total_usd": 0.0, "by_profile": {}, "timeline": []}
    found.setdefault("total_usd", 0.0)
    found.setdefault("by_profile", {})
    found.setdefault("timeline", [])
    return found


def save(ledger, path=LEDGER):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(ledger, indent=2, sort_keys=True) + "\n")


def track(ledger, running_usd_hour, moment=None, max_gap_s=MAX_GAP_S):
    """Add the machine time since the last look, at `running_usd_hour` per profile.

    The first look starts the clock and adds nothing: it has no earlier moment to measure from.
    """
    moment = moment or now_utc()
    stamp = moment.strftime(STAMP)
    last = ledger.get("updated")
    ledger["updated"] = stamp
    ledger.setdefault("started", stamp)
    if last:
        gap = min((moment - when(last)).total_seconds(), max_gap_s)
        if gap > 0:
            for profile, hourly in sorted(running_usd_hour.items()):
                cost = hourly * gap / 3600.0
                ledger["by_profile"][profile] = ledger["by_profile"].get(profile, 0.0) + cost
                ledger["total_usd"] += cost
    ledger["timeline"].append([stamp, round(ledger["total_usd"], 6)])
    return ledger


def total(ledger):
    """Everything spent: what this watch has counted, plus any bill it was seeded with."""
    return ledger.get("total_usd", 0.0) + ledger.get("before_usd", 0.0)


def at(ledger, moment):
    """What had been spent at `moment`: the last point at or before it, or None.

    A ledger that was seeded with an earlier bill carries that bill in every answer, so a run is
    told what the whole testbed had cost by the time it began, not only what this watch counted.
    """
    if isinstance(moment, str):
        moment = when(moment)
    reached = None
    for stamp, total in ledger.get("timeline", []):
        if when(stamp) <= moment:
            reached = total
        else:
            break
    return None if reached is None else reached + ledger.get("before_usd", 0.0)



def line(ledger, credit_usd=200.0):
    """One line a person can read in a watch log."""
    before = ledger.get("before_usd", 0.0)
    parts = ["spent about $%.2f of $%.0f" % (total(ledger), credit_usd)]
    if before:
        parts.append("$%.2f of it billed%s" % (
            before, " through %s" % ledger["before_through"] if ledger.get("before_through")
            else " before the watch began"))
    if ledger.get("started"):
        parts.append("since %s" % ledger["started"][:10])
    by = ledger.get("by_profile") or {}
    if by:
        parts.append(", ".join("%s $%.2f" % (p, c) for p, c in sorted(by.items())))
    return "; ".join(parts)


def billed(since="2026-09-01", run=subprocess.run):
    """(total, by day) of what Azure has charged, in the billing currency, from usage details."""
    show = run(["az", "account", "show", "--query", "id", "-o", "tsv"],
               capture_output=True, text=True, shell=True)
    if show.returncode != 0:
        raise RuntimeError("could not read the subscription: %s" % (show.stderr or "").strip())
    subscription = (show.stdout or "").strip()
    #: No & and no $ in the address: with a shell in the way, cmd.exe cuts a command at an
    #: ampersand and sh eats a dollar, and either one turns the bill into an error message. One
    #: page holds far more rows than this subscription makes in a month; `more` says if it did not.
    url = ("https://management.azure.com/subscriptions/%s/providers/Microsoft.Consumption/"
           "usageDetails?api-version=2023-05-01" % subscription)
    got = run(["az", "rest", "--method", "get", "--url", url],
              capture_output=True, text=True, shell=True)
    if got.returncode != 0:
        raise RuntimeError("could not read the bill: %s" % (got.stderr or "").strip())
    page = json.loads(got.stdout or "{}")
    total, by_day, currency = 0.0, {}, ""
    for row in page.get("value", []):
        p = row.get("properties", {})
        day = (p.get("date") or "")[:10]
        if day < since:
            continue
        cost = float(p.get("costInUSD") or p.get("cost") or 0.0)
        total += cost
        by_day[day] = by_day.get(day, 0.0) + cost
        currency = currency or "USD"
    return {"total_usd": total, "by_day": by_day, "currency": currency or "USD",
            "since": since, "rows": len(page.get("value", [])),
            "more": bool(page.get("nextLink"))}


def main(argv=None, out=None, run=subprocess.run):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="What the testbed has cost")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("show")
    p.add_argument("--ledger", default=LEDGER)
    p.add_argument("--credit-usd", type=float, default=200.0)
    p = sub.add_parser("billed")
    p.add_argument("--since", default="2026-09-01")
    p = sub.add_parser("seed", help="what had been billed before the watch began counting")
    p.add_argument("--usd", type=float, help="the figure, when Azure cannot be asked")
    p.add_argument("--from-bill", action="store_true", help="take it from Azure's own bill")
    p.add_argument("--since", default="2026-09-01")
    p.add_argument("--ledger", default=LEDGER)
    p.add_argument("--credit-usd", type=float, default=200.0)
    args = ap.parse_args(argv)
    try:
        if args.command == "show":
            ledger = load(args.ledger)
            print(line(ledger, args.credit_usd), file=out)
            if ledger.get("timeline"):
                print("the watch has been counting since %s, last at %s"
                      % (ledger["timeline"][0][0], ledger["updated"]), file=out)
            return 0
        if args.command == "seed":
            ledger = load(args.ledger)
            if args.from_bill:
                found = billed(args.since, run)
                ledger["before_usd"] = found["total_usd"]
                ledger["before_through"] = max(found["by_day"] or ["none"])
            elif args.usd is None:
                raise ValueError("seed needs --usd or --from-bill")
            else:
                ledger["before_usd"] = args.usd
            save(ledger, args.ledger)
            print(line(ledger, args.credit_usd), file=out)
            return 0
        found = billed(args.since, run)
        print("billed since %s: $%.2f over %d day(s)"
              % (found["since"], found["total_usd"], len(found["by_day"])), file=out)
        for day, cost in sorted(found["by_day"].items()):
            print("  %s  $%.2f" % (day, cost), file=out)
        if found["more"]:
            print("  (Azure had more rows than one page; this is what the first page holds)",
                  file=out)
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print("ERROR: %s" % exc, file=out)
        return 2


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
