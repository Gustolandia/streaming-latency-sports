#!/usr/bin/env python3
"""
analyze_depth.py
Turn the depth-suite runs into the H1 and H2 verdicts (see docs/measurement_model.md).

For each condition it computes the inversion rate -- the fraction of events whose broker
transport (consumer receipt minus broker acknowledgement) is negative, which is the physically
impossible measurement the whole paper is about -- then:

  H1 (E-B): inversion rate vs the true latency being measured (the injected netem delay).
            The model predicts it falls as the measured quantity grows.
  H2 (E-A): inversion rate vs achieved CPU utilisation. The model predicts an M/G/1 knee.

Transport is recomputed from the raw per-event data rather than trusted from a summary, because
the summary is exactly what hides the failure.

CLI:
    python scripts/analyze_depth.py --depth-dir docs/results/depth --runs-dir runs \
        --out docs/results/depth/model
"""
import argparse
import csv
import glob
import os
import re
import statistics as st
from pathlib import Path

# measurement_model lives beside this file.
import sys
sys.path.insert(0, str(Path(__file__).parent))
from measurement_model import check_h1, check_h2, spearman  # noqa: E402


def run_inversion(run_dir):
    """(negative events, total events) for one run, from raw per-event transport.

    Joins consumer receipt (t_consume_ns) to broker acknowledgement (t_broker_ack_ns) on
    event_id. A negative difference is an inversion. Returns (0, 0) if the run is unreadable, so
    a broken run contributes nothing rather than crashing the sweep.
    """
    cons = os.path.join(run_dir, "consumer_events.csv")
    prod = os.path.join(run_dir, "producer.csv")
    if not (os.path.exists(cons) and os.path.exists(prod)):
        return 0, 0
    ack = {}
    try:
        with open(prod, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                v = r.get("t_broker_ack_ns")
                if v not in (None, "", "None"):
                    ack[r["event_id"]] = int(v)
        neg = tot = 0
        with open(cons, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                a = ack.get(r["event_id"])
                recv = r.get("t_consume_ns")
                if a is not None and recv not in (None, "", "None"):
                    tot += 1
                    if int(recv) - a < 0:
                        neg += 1
        return neg, tot
    except (ValueError, KeyError, OSError):
        return 0, 0


def run_transport_median(run_dir):
    """Median broker transport in ms for one run, from raw per-event data.

    Same join as run_inversion, but keeps the values rather than counting negatives, so the
    between-backend difference can be compared across stamping modes (H3).
    """
    cons = os.path.join(run_dir, "consumer_events.csv")
    prod = os.path.join(run_dir, "producer.csv")
    if not (os.path.exists(cons) and os.path.exists(prod)):
        return None
    ack = {}
    try:
        with open(prod, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                v = r.get("t_broker_ack_ns")
                if v not in (None, "", "None"):
                    ack[r["event_id"]] = int(v)
        vals = []
        with open(cons, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                a = ack.get(r["event_id"])
                recv = r.get("t_consume_ns")
                if a is not None and recv not in (None, "", "None"):
                    vals.append((int(recv) - a) / 1e6)
        return st.median(vals) if vals else None
    except (ValueError, KeyError, OSError):
        return None


def condition_transport_by_backend(cond_dir, runs_dir):
    """Median transport per backend, as {'kafka': ms, 'redis': ms, 'kafka_n_runs': k, ...}.

    The estimator is the median of per-run medians, not the median of pooled events. That is
    deliberate -- runs differ in length, and pooling would weight a long run more heavily than a
    short one -- and it is recorded here because recomputing this quantity with the pooled
    estimator gives a visibly different answer (0.204 against 0.215 ms for the inline arm).

    The run counts are returned alongside because the artefact this feeds carried four medians
    and no sample size at all. A reader had no way to tell whether it came from twenty runs or
    from a script that failed and wrote defaults, which is exactly the gap that let a benchmark
    that never executed report a discard count of zero.
    """
    ts = condition_timestamp(cond_dir)
    if not ts:
        return {}
    out = {}
    for backend in ("kafka", "redis"):
        vals = []
        for run in glob.glob(os.path.join(runs_dir, f"concurrency_{ts}_{backend}_*")):
            if os.path.isdir(run):
                m = run_transport_median(run)
                if m is not None:
                    vals.append(m)
        if vals:
            out[backend] = st.median(vals)
            out[f"{backend}_n_runs"] = len(vals)
    return out


def condition_timestamp(cond_dir):
    """The run-id timestamp a condition's trials share, read from its concurrency subdir."""
    for sub in glob.glob(os.path.join(cond_dir, "concurrency_concurrency_*")):
        m = re.search(r"concurrency_(n\d+_\d{8}_\d{6})", os.path.basename(sub))
        if m:
            return m.group(1)
    return None


def condition_inversion(cond_dir, runs_dir):
    """Pooled inversion rate across every run belonging to a condition."""
    ts = condition_timestamp(cond_dir)
    if not ts:
        return None
    neg = tot = 0
    for run in glob.glob(os.path.join(runs_dir, f"concurrency_{ts}_*")):
        if os.path.isdir(run):
            n, t = run_inversion(run)
            neg += n
            tot += t
    return (neg / tot) if tot else None


def median_rho(cond_dir):
    """Median achieved utilisation from the condition's sampler trace."""
    u = os.path.join(cond_dir, "utilisation.csv")
    if not os.path.exists(u):
        return None
    vals = []
    with open(u, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                vals.append(float(r["rho"]))
            except (KeyError, TypeError, ValueError):
                continue
    return st.median(vals) if vals else None


def delay_from_tag(cond_dir):
    """Injected one-way delay in ms, parsed from an E-B condition directory name (d0, d20...)."""
    m = re.search(r"d(\d+)$", os.path.basename(cond_dir.rstrip("/")))
    return float(m.group(1)) if m else None


def n_from_tag(cond_dir):
    """Process count parsed from an E-A2 condition directory name (n1, n3, n6, n12)."""
    m = re.search(r"n(\d+)$", os.path.basename(cond_dir.rstrip("/")))
    return int(m.group(1)) if m else None


def collect(depth_dir, runs_dir):
    """Build the E-B (H1), E-A/E-A-sat (H2) and E-A2 (H4) tables from the completed runs.

    E-A-sat supersedes E-A where present: the first E-A never reached saturation, so if the
    saturation rerun exists its data is used for H2 instead.
    """
    eb, ea, ea2 = [], [], []
    for cond in sorted(glob.glob(os.path.join(depth_dir, "eb", "d*"))):
        inv = condition_inversion(cond, runs_dir)
        d = delay_from_tag(cond)
        if inv is not None and d is not None:
            eb.append({"t_true_ms": d, "inversion_rate": inv})

    # H2 uses the saturation sweep plus the knee-fill when present; both measure system-wide
    # utilisation with no core pinning, so they pool. The original `ea` phase is used only as a
    # fallback: it was taskset-pinned while utilisation was measured across all cores, so its
    # rho is diluted and not comparable.
    ea_phases = [p for p in ("ea_sat", "ea_knee")
                 if glob.glob(os.path.join(depth_dir, p, "*"))] or ["ea"]
    for phase in ea_phases:
        for cond in sorted(glob.glob(os.path.join(depth_dir, phase, "*"))):
            if os.path.isdir(cond):
                inv = condition_inversion(cond, runs_dir)
                rho = median_rho(cond)
                if inv is not None and rho is not None:
                    ea.append({"rho": rho, "inversion_rate": inv})

    for cond in sorted(glob.glob(os.path.join(depth_dir, "ea2", "n*"))):
        inv = condition_inversion(cond, runs_dir)
        n = n_from_tag(cond)
        if inv is not None and n is not None:
            ea2.append({"n_feeds": n, "inversion_rate": inv})
    return eb, ea, ea2


def _write(rows, path, fields):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    import pandas as pd
    ap = argparse.ArgumentParser(description="Fit H1/H2 from the depth suite")
    ap.add_argument("--depth-dir", default="docs/results/depth")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--out", default="docs/results/depth/model")
    args = ap.parse_args(argv)

    eb, ea, ea2 = collect(args.depth_dir, args.runs_dir)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print("== E-B: effect-size sweep (H1) ==")
    for r in sorted(eb, key=lambda x: x["t_true_ms"]):
        print(f"  delay {r['t_true_ms']:5.0f} ms  ->  inversion rate {r['inversion_rate']:.4f}")
    print("== E-A: utilisation sweep (H2) ==")
    for r in sorted(ea, key=lambda x: x["rho"]):
        print(f"  rho {r['rho']:.3f}  ->  inversion rate {r['inversion_rate']:.4f}")
    print("== E-A2: process-count sweep (H4) ==")
    for r in sorted(ea2, key=lambda x: x["n_feeds"]):
        print(f"  N={r['n_feeds']:2d}  ->  inversion rate {r['inversion_rate']:.4f}")

    # H3: does the between-backend difference depend on how the acknowledgement is stamped?
    # ec3 is the real test -- kafka_producer.py's own --ack-stamp, so `inline` genuinely stamps
    # on the calling thread the way redis_producer.py does. ec2 is the earlier attempt, which
    # compared kafka-python against confluent-kafka; both stamp in callbacks, so it never
    # created the symmetric condition and can only be reported as untested. Prefer ec3.
    h3_phase = "ec3" if glob.glob(os.path.join(args.depth_dir, "ec3", "*")) else "ec2"
    symmetric = h3_phase == "ec3"
    print(f"== E-C3: stamping comparison (H3) ==" if symmetric
          else "== E-C2: stamping comparison (H3, asymmetric pair -- untested) ==")
    h3 = {}
    h3_rows = []
    for mode in ("callback", "inline"):
        cond = os.path.join(args.depth_dir, h3_phase, mode)
        if os.path.isdir(cond):
            t = condition_transport_by_backend(cond, args.runs_dir)
            if "kafka" in t and "redis" in t:
                diff = t["kafka"] - t["redis"]
                h3[mode] = diff
                h3_rows.append({"stamp": mode, "kafka_ms": round(t["kafka"], 4),
                                "redis_ms": round(t["redis"], 4), "difference_ms": round(diff, 4),
                                "n_runs_kafka": t.get("kafka_n_runs", 0),
                                "n_runs_redis": t.get("redis_n_runs", 0)})
                print(f"  {mode:9s}: kafka {t['kafka']:.3f} ms, redis {t['redis']:.3f} ms, "
                      f"difference {diff:+.3f} ms")
    if len(h3) == 2:
        shrink = abs(h3["callback"]) - abs(h3["inline"])
        print(f"  |difference| callback {abs(h3['callback']):.3f} -> inline "
              f"{abs(h3['inline']):.3f} ms  (change {shrink:+.3f})")
        if symmetric:
            print(f"  H3 stamping rule: {'SUPPORTED' if shrink > 0 else 'NOT SUPPORTED'} "
                  f"(the between-backend gap "
                  f"{'shrinks' if shrink > 0 else 'does not shrink'} when both endpoints stamp "
                  f"on the calling thread)")
            # Written whatever the verdict: it is the measurement, not the confirmation.
            _write(h3_rows, out / "ec3_stamping.csv",
                   ["stamp", "kafka_ms", "redis_ms", "difference_ms",
                    "n_runs_kafka", "n_runs_redis"])
        else:
            print("  H3 stamping rule: UNTESTED (both arms stamp in callbacks, so the "
                  "symmetric condition was never created)")

    verdicts = {}
    if len(eb) >= 3:
        _write(eb, out / "eb_effect_size.csv", ["t_true_ms", "inversion_rate"])
        verdicts["H1"] = check_h1(pd.DataFrame(eb))
    if len(ea) >= 3:
        _write(ea, out / "ea_utilisation.csv", ["rho", "inversion_rate"])
        verdicts["H2"] = check_h2(pd.DataFrame(ea))
    if len(ea2) >= 3:
        _write(ea2, out / "ea2_process_count.csv", ["n_feeds", "inversion_rate"])
        rho = spearman([r["n_feeds"] for r in ea2], [r["inversion_rate"] for r in ea2])
        verdicts["H4"] = {"hypothesis": "H4 oversubscription rule", "n_points": len(ea2),
                          "spearman": rho, "supported": bool(rho > 0)}

    print("\n== VERDICTS ==")
    for key, v in verdicts.items():
        print(f"{key} {v['hypothesis']}: "
              f"{'SUPPORTED' if v['supported'] else 'NOT SUPPORTED'} "
              f"(spearman {v['spearman']:.3f}, n={v['n_points']})")
        if key == "H2":
            print(f"   shape: R^2 M/G/1 {v['r2_mg1']:.3f} vs linear {v['r2_linear']:.3f}")
    if not verdicts:
        print("insufficient data for any hypothesis")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
