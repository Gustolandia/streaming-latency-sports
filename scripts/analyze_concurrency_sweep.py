#!/usr/bin/env python3
"""
analyze_concurrency_sweep.py
Comprehensive analysis of concurrency sweep results for S1-S5 scenarios.

Usage:
    python analyze_concurrency_sweep.py --handoff-only --output-dir <dir>
"""

import argparse
import json
import sys
from pathlib import Path
import re

import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats

sns.set_style("whitegrid")
plt.rcParams.update({
    'font.family': 'serif',
    'font.size': 12,
    'axes.labelsize': 12,
    'axes.titlesize': 14,
    'xtick.labelsize': 10,
    'ytick.labelsize': 10,
    'legend.fontsize': 10,
    'figure.figsize': (10, 6),
    'figure.dpi': 300,
})

SCENARIO_MAP = {'s1': 'S1', 's2': 'S2', 's2full': 'S3', 's2sf12': 'S4', 's2sf12j2': 'S5'}

PREFIX_MAP = {
    '001322': 's1', '001416': 's2', '001522': 's2full',
    '001613': 's2sf12', '001712': 's2sf12j2', '001814': 's1', '001910': 's2',
    '002010': 's1', '002110': 's2', '002229': 's2full',
    '002350': 's2sf12', '002544': 's2sf12j2',
    '002749': 's1', '002920': 's2',
}

COLORS = {'kafka': '#1f77b4', 'redis': '#ff7f0e'}


def get_scenario(prefix):
    return PREFIX_MAP.get(prefix, 'unknown')


def load_run_data(runs):
    all_data = []
    for run_dir in runs:
        tti_file = run_dir / "tti_summary.json"
        meta_file = run_dir / "meta.json"
        if not tti_file.exists():
            continue
        try:
            with open(tti_file, 'r', encoding='utf-8-sig') as f:
                tti = json.load(f)
        except:
            continue
        backend = "unknown"
        if meta_file.exists():
            try:
                with open(meta_file, 'r', encoding='utf-8-sig') as f:
                    meta = json.load(f)
                backend = meta.get("backend", "unknown")
            except:
                pass
        match = re.search(r'_(\d{6})_', run_dir.name)
        prefix = match.group(1) if match else None
        scenario = get_scenario(prefix) if prefix else "unknown"
        n_match = re.search(r'n(\d+)', run_dir.name)
        n = int(n_match.group(1)) if n_match else None
        feed_match = re.search(r'feed(\d+)', run_dir.name)
        feed = int(feed_match.group(1)) if feed_match else None
        if "tti_ms" in tti and isinstance(tti["tti_ms"], dict):
            t = tti["tti_ms"]
            p50, p95, p99 = t.get("p50"), t.get("p95"), t.get("p99")
            max_t, mean_t, std_t, min_t = t.get("max"), t.get("mean"), t.get("std"), t.get("min")
        else:
            p50 = tti.get("tti_ms_p50")
            p95 = tti.get("tti_ms_p95")
            p99 = tti.get("tti_ms_p99")
            max_t = tti.get("tti_ms_max")
            mean_t = tti.get("tti_ms_mean")
            std_t = tti.get("tti_ms_std")
            min_t = tti.get("tti_ms_min")
        n_prod = tti.get("n_producer") or tti.get("n_produced")
        n_cons = tti.get("n_consumer") or tti.get("n_consumed")
        n_mat = tti.get("n_matched")
        all_data.append({
            "run_id": run_dir.name, "backend": backend, "scenario": scenario,
            "scenario_name": SCENARIO_MAP.get(scenario, scenario), "n": n, "feed": feed,
            "tti_p50": p50, "tti_p95": p95, "tti_p99": p99,
            "tti_max": max_t, "tti_mean": mean_t, "tti_std": std_t, "tti_min": min_t,
            "n_producer": n_prod, "n_consumer": n_cons, "n_matched": n_mat,
        })
    return pd.DataFrame(all_data)


def discover_runs(runs_dir):
    runs = []
    pattern = re.compile(r'concurrency_n\d+_\d{8}_\d{6}_(kafka|redis)_feed\d+_rep\d+')
    for item in runs_dir.iterdir():
        if item.is_dir() and pattern.match(item.name):
            runs.append(item)
    return sorted(runs)


def filter_handoff(runs):
    prefixes = list(PREFIX_MAP.keys())
    filtered = []
    for run in runs:
        match = re.search(r'_(\d{6})_', run.name)
        if match and match.group(1) in prefixes:
            filtered.append(run)
    return filtered


def main():
    parser = argparse.ArgumentParser(description='Analyze concurrency sweep')
    parser.add_argument('--runs-dir', default='runs')
    parser.add_argument('--output-dir', default='docs/results/concurrency_sweep_20260613')
    parser.add_argument('--handoff-only', action='store_true')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    
    runs_dir = Path(args.runs_dir)
    output_dir = Path(args.output_dir)
    
    if output_dir.exists() and not args.force:
        print(f"Output exists: {output_dir}. Use --force to overwrite.")
        sys.exit(1)
    
    print("=" * 60)
    print("Concurrency Sweep Analysis")
    print("=" * 60)
    
    all_runs = discover_runs(runs_dir)
    print(f"Found {len(all_runs)} concurrency runs")
    runs = filter_handoff(all_runs) if args.handoff_only else all_runs
    print(f"Analyzing {len(runs)} runs")
    
    df = load_run_data(runs)
    print(f"Loaded {len(df)} valid runs")
    df = df.dropna(subset=['tti_p50', 'backend', 'scenario', 'n'])
    
    if df.empty:
        print("No valid data!")
        sys.exit(1)
    
    print("\nScenario Distribution:")
    for scenario, count in df['scenario'].value_counts().items():
        print(f"  {SCENARIO_MAP.get(scenario, scenario)}: {count} runs")
    
    print("\nConcurrency Distribution:")
    for n, count in df['n'].value_counts().sort_index().items():
        print(f"  N={int(n)}: {count} runs")
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Scenario Comparison
    print("\nGenerating scenario comparison...")
    comp_data = []
    for scenario in sorted(df['scenario'].unique()):
        sdf = df[df['scenario'] == scenario]
        for backend in ['kafka', 'redis']:
            bdf = sdf[sdf['backend'] == backend]
            if len(bdf) == 0:
                continue
            comp_data.append({
                'Scenario': SCENARIO_MAP.get(scenario, scenario),
                'Backend': backend.capitalize(),
                'Runs': len(bdf),
                'TTI_p50_ms': bdf['tti_p50'].mean(),
                'TTI_p95_ms': bdf['tti_p95'].mean(),
                'TTI_p99_ms': bdf['tti_p99'].mean(),
                'Events_Matched': int(bdf['n_matched'].mean()),
                'Match_Rate_Pct': (bdf['n_matched'].mean() / bdf['n_producer'].mean() * 100) if bdf['n_producer'].mean() > 0 else 0,
            })
    comp_df = pd.DataFrame(comp_data)
    comp_df.to_csv(output_dir / 'scenario_comparison.csv', index=False)
    print(f"  Saved scenario_comparison.csv")
    
    # 2. Scaling Analysis
    print("Generating scaling analysis...")
    scale_data = []
    for n in sorted(df['n'].unique()):
        for scenario in sorted(df['scenario'].unique()):
            for backend in ['kafka', 'redis']:
                subset = df[(df['n'] == n) & (df['scenario'] == scenario) & (df['backend'] == backend)]
                if len(subset) == 0:
                    continue
                scale_data.append({
                    'N': int(n), 'Scenario': SCENARIO_MAP.get(scenario, scenario),
                    'Backend': backend.capitalize(),
                    'TTI_p50_ms': subset['tti_p50'].mean(),
                    'TTI_p50_std': subset['tti_p50'].std(),
                })
    scale_df = pd.DataFrame(scale_data)
    scale_df.to_csv(output_dir / 'scaling_analysis.csv', index=False)
    
    plt.figure(figsize=(12, 8))
    for scenario in sorted(df['scenario'].unique()):
        sdata = scale_df[scale_df['Scenario'] == SCENARIO_MAP.get(scenario, scenario)]
        for backend in ['Kafka', 'Redis']:
            bdata = sdata[sdata['Backend'] == backend]
            if len(bdata) == 0:
                continue
            plt.errorbar(bdata['N'], bdata['TTI_p50_ms'], yerr=bdata['TTI_p50_std'],
                        label=f"{SCENARIO_MAP.get(scenario, scenario)} - {backend}",
                        marker='o' if backend == 'Kafka' else 's', capsize=5, linewidth=2)
    plt.title('TTI p50 vs Concurrency Level')
    plt.xlabel('Concurrency Level (N)')
    plt.ylabel('TTI p50 (ms)')
    plt.grid(True, alpha=0.3)
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.tight_layout()
    plt.savefig(output_dir / 'tti_scaling.png', dpi=300, bbox_inches='tight')
    plt.close()
    print(f"  Saved tti_scaling.png")
    
    # 3. Backend Comparison
    print("Generating backend comparison...")
    plt.figure(figsize=(14, 8))
    scenarios = sorted(df['scenario'].unique())
    positions, plot_data, labels = [], [], []
    for i, scenario in enumerate(scenarios):
        sdf = df[df['scenario'] == scenario]
        for j, backend in enumerate(['kafka', 'redis']):
            data = sdf[sdf['backend'] == backend]['tti_p50'].dropna()
            if len(data) > 0:
                pos = i * 3 + j + 1
                positions.append(pos)
                plot_data.append(data.values)
                labels.append(f"{SCENARIO_MAP.get(scenario, scenario)}\n{backend.upper()}")
    if plot_data:
        bp = plt.boxplot(plot_data, positions=positions, patch_artist=True)
        for patch, backend in zip(bp['boxes'], ['kafka', 'redis'] * len(scenarios)):
            patch.set_facecolor(COLORS.get(backend))
        plt.xticks(positions, labels)
        plt.title('TTI p50 Distribution by Scenario and Backend')
        plt.ylabel('TTI p50 (ms)')
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(output_dir / 'backend_boxplot.png', dpi=300, bbox_inches='tight')
        plt.close()
    print(f"  Saved backend_boxplot.png")
    
    # 4. Statistical Comparison
    print("Generating statistical comparison...")
    stats_data = []
    for scenario in scenarios:
        sdf = df[df['scenario'] == scenario]
        for metric in ['tti_p50', 'tti_p95', 'tti_p99']:
            k = sdf[sdf['backend'] == 'kafka'][metric].dropna()
            r = sdf[sdf['backend'] == 'redis'][metric].dropna()
            if len(k) > 0 and len(r) > 0:
                t_stat, p_val = stats.ttest_ind(k, r)
                stats_data.append({
                    'Scenario': SCENARIO_MAP.get(scenario, scenario),
                    'Metric': metric.replace('tti_', 'TTI ').replace('_', ' ').title(),
                    'Kafka_Mean': k.mean(), 'Redis_Mean': r.mean(),
                    'Diff': r.mean() - k.mean(),
                    'Diff_Pct': ((r.mean() - k.mean()) / k.mean() * 100) if k.mean() > 0 else 0,
                    'P_Value': p_val, 'Significant': 'Yes' if p_val < 0.05 else 'No',
                })
    stats_df = pd.DataFrame(stats_data)
    stats_df.to_csv(output_dir / 'statistical_comparison.csv', index=False)
    print(f"  Saved statistical_comparison.csv")
    
    # 5. Event Analysis
    print("Generating event analysis...")
    df['match_rate'] = df['n_matched'] / df['n_producer'] * 100
    event_data = []
    for scenario in scenarios:
        sdf = df[df['scenario'] == scenario]
        for backend in ['kafka', 'redis']:
            bdf = sdf[sdf['backend'] == backend]
            if len(bdf) > 0:
                event_data.append({
                    'Scenario': SCENARIO_MAP.get(scenario, scenario),
                    'Backend': backend.capitalize(),
                    'Avg_Events': int(bdf['n_matched'].mean()),
                    'Match_Rate': bdf['match_rate'].mean(),
                })
    event_df = pd.DataFrame(event_data)
    event_df.to_csv(output_dir / 'event_analysis.csv', index=False)
    
    # For plotting, ensure we have matching data for both backends
    # Get scenarios that have both backends
    plot_scenarios = []
    for scenario in scenarios:
        sdf = event_df[event_df['Scenario'] == SCENARIO_MAP.get(scenario, scenario)]
        backends = sdf['Backend'].unique()
        if len(backends) >= 1:
            plot_scenarios.append(SCENARIO_MAP.get(scenario, scenario))
    
    if len(plot_scenarios) > 0:
        plt.figure(figsize=(12, 6))
        x = range(len(plot_scenarios))
        width = 0.35
        
        # Get data for each backend
        k_rates = []
        r_rates = []
        for scenario in plot_scenarios:
            sdf = event_df[event_df['Scenario'] == scenario]
            k_rate = sdf[sdf['Backend'] == 'Kafka']['Match_Rate'].values
            r_rate = sdf[sdf['Backend'] == 'Redis']['Match_Rate'].values
            k_rates.append(k_rate[0] if len(k_rate) > 0 else 0)
            r_rates.append(r_rate[0] if len(r_rate) > 0 else 0)
        
        plt.bar([i - width/2 for i in x], k_rates, width, label='Kafka', color=COLORS['kafka'])
        plt.bar([i + width/2 for i in x], r_rates, width, label='Redis', color=COLORS['redis'])
        plt.title('Event Match Rate by Scenario and Backend')
        plt.xlabel('Scenario')
        plt.ylabel('Match Rate (%)')
        plt.xticks(x, plot_scenarios)
        plt.legend()
        plt.grid(True, alpha=0.3, axis='y')
        plt.tight_layout()
        plt.savefig(output_dir / 'match_rate_bars.png', dpi=300, bbox_inches='tight')
        plt.close()
    print(f"  Saved match_rate_bars.png")
    
    # 6. Summary Report
    print("Generating summary report...")
    with open(output_dir / 'SUMMARY.md', 'w') as f:
        f.write('# Concurrency Sweep Analysis\n\n')
        f.write(f'## Overview\n- **Date**: 2026-06-13\n')
        f.write(f'- **Total Runs**: {len(df)}\n')
        f.write(f'- **Scenarios**: {len(scenarios)}\n')
        f.write(f'- **Backends**: Kafka, Redis\n')
        f.write(f'- **Concurrency Levels**: {sorted(df["n"].unique())}\n\n')
        f.write('## Key Metrics\n')
        f.write(f'- **Avg TTI p50**: {df["tti_p50"].mean():.2f} ms\n')
        f.write(f'- **Avg TTI p95**: {df["tti_p95"].mean():.2f} ms\n')
        f.write(f'- **Avg Match Rate**: {df["match_rate"].mean():.2f}%\n\n')
        f.write('## Scenario Definitions\n')
        for key, name in SCENARIO_MAP.items():
            f.write(f'- **{name}**: {key}\n')
        f.write('\n## Generated Files\n')
        for fn in ['scenario_comparison.csv', 'scaling_analysis.csv', 
                   'statistical_comparison.csv', 'event_analysis.csv',
                   'tti_scaling.png', 'backend_boxplot.png', 'match_rate_bars.png']:
            f.write(f'- `{fn}`\n')
    print(f"  Saved SUMMARY.md")
    
    print("\n" + "=" * 60)
    print("Analysis Complete!")
    print("=" * 60)
    files = [f for f in output_dir.rglob('*') if f.is_file()]
    print(f"Generated {len(files)} files in {output_dir}")
    for f in sorted(files):
        print(f"  {f.name}")


if __name__ == '__main__':  # pragma: no cover - dispatch only; main() is tested directly
    main()
