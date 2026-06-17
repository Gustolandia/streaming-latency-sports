#!/usr/bin/env python3
"""
analyze_batches_1_2_3.py
Comprehensive analysis of the 120 multi-broker runs (batches 1-3).
Addresses Issues 2, 3, 4, and 5 from REVISION_PLAN_COMPACT.md.

Analysis includes:
- RQ1: Architecture impact (Kafka vs Redis)
- RQ2: Concurrency scaling (N=5, 10, 20)
- RQ3: Latency-consistency trade-off
- RQ4: Sports-specific performance
- Throughput, message sizes, protocol overhead (Issue 3)
- Statistical analysis with corrections (Issue 4)
- Actionability metrics (Issue 5)

Usage:
    python analyze_batches_1_2_3.py --output-dir docs/results/batches_1_2_3_analysis
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats

# Configuration
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

COLORS = {'kafka': '#1f77b4', 'redis': '#ff7f0e'}
SCENARIO_MAP = {'s1': 'S1', 's2': 'S2', 's2full': 'S3', 's2sf12': 'S4', 's2sf12j2': 'S5'}
SCENARIO_NAMES = {
    's1': 'S1 (Simple)',
    's2': 'S2 (Full)', 
    's2full': 'S3 (Staleness)',
    's2sf12': 'S4 (Parameter)',
    's2sf12j2': 'S5 (Resource)'
}

# Hypotheses from REVISION_PLAN_COMPACT.md
HYPOTHESES = {
    'RQ1': {
        'H0': 'μ_TTI_Kafka = μ_TTI_Redis',
        'H1': 'μ_TTI_Kafka > μ_TTI_Redis',
        'H2': 'μ_TTI_Kafka < μ_TTI_Redis',
        'test': 'Mann-Whitney U test',
        'expected': 'H1 (Redis outperforms Kafka)',
    },
    'RQ2': {
        'H0': 'TTI is independent of concurrency level N',
        'H1': 'TTI increases monotonically with concurrency level N',
        'H2': 'TTI remains constant across N=5, 10, 20',
        'test': 'Kruskal-Wallis test',
        'expected': 'H2 (Excellent scaling)',
    },
    'RQ3': {
        'match_rate_H0': 'Match rate = 100% for all configurations',
        'match_rate_H1': 'Match rate > 99.9% for all configurations',
        'match_rate_H2': 'Match rate varies by configuration',
        'consistency_H3_1': 'μ_TTI_acks=all > μ_TTI_acks=1',
        'consistency_H3_2': 'μ_TTI_AOF=always > μ_TTI_AOF=1s',
        'test': 'Chi-square test or Fisher exact test, Paired t-test or Wilcoxon',
    },
    'RQ4': {
        'H0': 'TTI distribution is the same across all scenarios',
        'H1': 'TTI distribution differs by scenario',
        'H4_1': 'μ_TTI_S5 > μ_TTI_S1',
        'H4_2': 'σ_TTI_S5 > σ_TTI_S1',
        'test': 'Kolmogorov-Smirnov test, One-way ANOVA or Kruskal-Wallis',
    }
}


def extract_config_from_run_id(run_id):
    """Extract configuration parameters from run directory name."""
    # Pattern: batch{123}_YYYYMMDD_{backend}_{config}_{scenario}_n{N}_rep{replication}
    pattern = r'batch(\d+)_(\d{8})_(kafka|redis)_(single|cluster)_([a-z0-9]+)_n(\d+)_rep(\d+)'
    match = re.search(pattern, run_id)
    if match:
        return {
            'batch': int(match.group(1)),
            'date': match.group(2),
            'backend': match.group(3),
            'config': match.group(4),
            'scenario': match.group(5),
            'n': int(match.group(6)),
            'rep': int(match.group(7)),
        }
    return None


def load_all_batch_runs(batch_pattern='batch[123]_*'):
    """Load all run data from batch directories."""
    runs_dir = Path('runs')
    all_data = []
    
    run_dirs = sorted(runs_dir.glob(batch_pattern))
    print(f"Found {len(run_dirs)} run directories matching '{batch_pattern}'")
    
    for run_dir in run_dirs:
        tti_file = run_dir / "tti_summary.json"
        meta_file = run_dir / "meta.json"
        producer_file = run_dir / "producer.csv"
        consumer_file = run_dir / "consumer.csv"
        
        if not tti_file.exists():
            print(f"  WARNING: {run_dir.name} missing tti_summary.json")
            continue
            
        try:
            # Load tti_summary.json
            with open(tti_file, 'r', encoding='utf-8-sig') as f:
                tti = json.load(f)
            
            # Load meta.json
            meta = {}
            if meta_file.exists():
                with open(meta_file, 'r', encoding='utf-8-sig') as f:
                    meta = json.load(f)
            
            # Extract configuration from run_id
            config = extract_config_from_run_id(run_dir.name)
            if not config:
                print(f"  WARNING: Could not parse config from {run_dir.name}")
                continue
            
            # Extract TTI values
            tti_ms = tti.get("tti_ms")
            if isinstance(tti_ms, dict):
                p50 = tti_ms.get("p50")
                p95 = tti_ms.get("p95")
                p99 = tti_ms.get("p99")
                max_tti = tti_ms.get("max")
                mean_tti = tti_ms.get("mean")
                std_tti = tti_ms.get("std")
                min_tti = tti_ms.get("min")
            else:
                p50 = tti.get("tti_ms_p50")
                p95 = tti.get("tti_ms_p95")
                p99 = tti.get("tti_ms_p99")
                max_tti = tti.get("tti_ms_max")
                mean_tti = tti.get("tti_ms_mean")
                std_tti = tti.get("tti_ms_std")
                min_tti = tti.get("tti_ms_min")
            
            # Extract counts
            n_prod = tti.get("n_produced") or tti.get("n_producer")
            n_cons = tti.get("n_consumed") or tti.get("n_consumer")
            n_mat = tti.get("n_matched")
            
            # Calculate match rate
            match_rate = (n_mat / n_prod * 100) if n_prod and n_prod > 0 else 0
            
            # Load producer and consumer CSV to get message sizes
            producer_size = 0
            consumer_size = 0
            throughput = 0
            
            if producer_file.exists():
                producer_size = producer_file.stat().st_size
                try:
                    df_prod = pd.read_csv(producer_file)
                    if len(df_prod) > 0 and 't_sim_seconds' in df_prod.columns:
                        duration = df_prod['t_sim_seconds'].max()
                        if duration > 0:
                            throughput = len(df_prod) / duration
                except:
                    pass
            
            if consumer_file.exists():
                consumer_size = consumer_file.stat().st_size
            
            # Calculate average message size
            avg_msg_size = (producer_size / n_prod) if n_prod and n_prod > 0 else 0
            
            # Get actionability metrics from tti_summary if available
            actionability = tti.get("actionability", {})
            if actionability:
                pct_under_100ms = actionability.get("100", 0) * 100
                pct_under_500ms = actionability.get("500", 0) * 100
                pct_under_1s = actionability.get("1000", 0) * 100
                pct_under_5s = actionability.get("5000", 0) * 100
            else:
                # Calculate from tti_ms if available
                pct_under_100ms = 0
                pct_under_500ms = 0
                pct_under_1s = 0
                pct_under_5s = 0
            
            all_data.append({
                'run_id': run_dir.name,
                'batch': config['batch'],
                'backend': config['backend'],
                'config': config['config'],
                'scenario': config['scenario'],
                'scenario_name': SCENARIO_NAMES.get(config['scenario'], config['scenario']),
                'n': config['n'],
                'rep': config['rep'],
                'p50': p50,
                'p95': p95,
                'p99': p99,
                'max': max_tti,
                'mean': mean_tti,
                'std': std_tti,
                'min': min_tti,
                'n_produced': n_prod,
                'n_consumed': n_cons,
                'n_matched': n_mat,
                'match_rate_pct': match_rate,
                'producer_size_bytes': producer_size,
                'consumer_size_bytes': consumer_size,
                'avg_msg_size_bytes': avg_msg_size,
                'throughput_events_per_sec': throughput,
                'pct_under_100ms': pct_under_100ms,
                'pct_under_500ms': pct_under_500ms,
                'pct_under_1s': pct_under_1s,
                'pct_under_5s': pct_under_5s,
            })
        except Exception as e:
            print(f"  ERROR loading {run_dir.name}: {e}")
            continue
    
    return pd.DataFrame(all_data)


def run_hypothesis_tests(df):
    """Run all hypothesis tests and return results."""
    results = {}
    
    # RQ1: Architecture Impact (Kafka vs Redis)
    print("\n" + "="*80)
    print("RQ1: Architecture Impact Tests")
    print("="*80)
    
    kafka_df = df[df['backend'] == 'kafka']
    redis_df = df[df['backend'] == 'redis']
    
    # Mann-Whitney U test for p50
    u_stat, p_value = stats.mannwhitneyu(
        kafka_df['p50'].dropna(),
        redis_df['p50'].dropna(),
        alternative='two-sided'
    )
    
    # Cohen's d effect size
    n1 = len(kafka_df['p50'].dropna())
    n2 = len(redis_df['p50'].dropna())
    pooled_std = np.sqrt(((n1-1)*kafka_df['p50'].std()**2 + (n2-1)*redis_df['p50'].std()**2) / (n1+n2-2))
    cohen_d = (kafka_df['p50'].mean() - redis_df['p50'].mean()) / pooled_std if pooled_std > 0 else 0
    
    results['RQ1'] = {
        'test': 'Mann-Whitney U',
        'u_statistic': u_stat,
        'p_value': p_value,
        'cohen_d': cohen_d,
        'kafka_mean_p50': kafka_df['p50'].mean(),
        'redis_mean_p50': redis_df['p50'].mean(),
        'improvement_pct': ((kafka_df['p50'].mean() - redis_df['p50'].mean()) / kafka_df['p50'].mean()) * 100,
        'conclusion': 'H1: Redis has significantly lower TTI' if p_value < 0.05 and kafka_df['p50'].mean() > redis_df['p50'].mean() else 'H0: No significant difference',
    }
    
    print(f"  Mann-Whitney U: U={u_stat:.2f}, p={p_value:.4f}")
    print(f"  Cohen's d: {cohen_d:.3f}")
    print(f"  Kafka mean p50: {kafka_df['p50'].mean():.2f} ms")
    print(f"  Redis mean p50: {redis_df['p50'].mean():.2f} ms")
    print(f"  Improvement: {results['RQ1']['improvement_pct']:.1f}%")
    print(f"  Conclusion: {results['RQ1']['conclusion']}")
    
    # RQ2: Concurrency Scaling
    print("\n" + "="*80)
    print("RQ2: Concurrency Scaling Tests")
    print("="*80)
    
    n_levels = sorted(df['n'].unique())
    n_data = [df[df['n'] == n]['p50'].dropna() for n in n_levels]
    
    # Kruskal-Wallis test
    h_stat, p_value = stats.kruskal(*n_data)
    
    # Pairwise comparisons with Bonferroni correction
    from itertools import combinations
    pairwise_results = []
    alpha = 0.05
    num_comparisons = len(list(combinations(n_levels, 2)))
    bonferroni_alpha = alpha / num_comparisons
    
    for (n1, n2) in combinations(n_levels, 2):
        data1 = df[df['n'] == n1]['p50'].dropna()
        data2 = df[df['n'] == n2]['p50'].dropna()
        u_stat, p_val = stats.mannwhitneyu(data1, data2, alternative='two-sided')
        pairwise_results.append({
            'n1': n1, 'n2': n2,
            'u_stat': u_stat, 'p_value': p_val,
            'significant': p_val < bonferroni_alpha
        })
        print(f"  N={n1} vs N={n2}: U={u_stat:.2f}, p={p_val:.4f}, significant={p_val < bonferroni_alpha}")
    
    results['RQ2'] = {
        'test': 'Kruskal-Wallis',
        'h_statistic': h_stat,
        'p_value': p_value,
        'pairwise': pairwise_results,
        'conclusion': 'H2: TTI remains constant across N=5,10,20' if h_stat < stats.chi2.ppf(0.95, len(n_levels)-1) else 'H1: TTI varies with concurrency',
    }
    
    print(f"  Kruskal-Wallis H={h_stat:.2f}, p={p_value:.4f}")
    print(f"  Conclusion: {results['RQ2']['conclusion']}")
    
    # RQ3: Latency-Consistency Trade-off
    print("\n" + "="*80)
    print("RQ3: Latency-Consistency Trade-off Tests")
    print("="*80)
    
    # Match rate test
    match_rates = df['match_rate_pct']
    all_100 = (match_rates == 100).all()
    all_above_999 = (match_rates >= 99.9).all()
    
    results['RQ3'] = {
        'match_rate_all_100': all_100,
        'match_rate_all_above_999': all_above_999,
        'mean_match_rate': match_rates.mean(),
        'min_match_rate': match_rates.min(),
        'conclusion_match': 'H1: All configs >99.9%' if all_above_999 else ('H0: All configs =100%' if all_100 else 'H2: Match rate varies'),
    }
    
    print(f"  Mean match rate: {match_rates.mean():.2f}%")
    print(f"  Min match rate: {match_rates.min():.2f}%")
    print(f"  All 100%: {all_100}")
    print(f"  All >99.9%: {all_above_999}")
    print(f"  Conclusion: {results['RQ3']['conclusion_match']}")
    
    # RQ4: Sports-Specific Performance
    print("\n" + "="*80)
    print("RQ4: Sports-Specific Performance Tests")
    print("="*80)
    
    scenarios = sorted(df['scenario'].unique())
    scenario_data = [df[df['scenario'] == s]['p50'].dropna() for s in scenarios]
    
    # Kolmogorov-Smirnov test for distribution differences
    ks_results = []
    for i, s1 in enumerate(scenarios):
        for j, s2 in enumerate(scenarios):
            if i < j:
                d_stat, p_val = stats.ks_2samp(scenario_data[i], scenario_data[j])
                ks_results.append({
                    'scenario1': s1, 'scenario2': s2,
                    'd_statistic': d_stat, 'p_value': p_val,
                    'significant': p_val < bonferroni_alpha
                })
                print(f"  {s1} vs {s2}: D={d_stat:.3f}, p={p_val:.4f}")
    
    # Check S5 vs S1
    s5_df = df[df['scenario'] == 's2sf12j2']
    s1_df = df[df['scenario'] == 's1']
    if len(s5_df) > 0 and len(s1_df) > 0:
        t_stat, p_val = stats.ttest_ind(s5_df['p50'].dropna(), s1_df['p50'].dropna(), equal_var=False)
        results['RQ4_H4_1'] = {
            'test': 'Welch t-test',
            't_statistic': t_stat,
            'p_value': p_val,
            's5_mean': s5_df['p50'].mean(),
            's1_mean': s1_df['p50'].mean(),
            'conclusion': 'H4_1: μ_TTI_S5 > μ_TTI_S1' if p_val < 0.05 and s5_df['p50'].mean() > s1_df['p50'].mean() else 'H0: No difference',
        }
        print(f"\n  S5 vs S1 (H4_1): t={t_stat:.3f}, p={p_val:.4f}")
        print(f"  S5 mean p50: {s5_df['p50'].mean():.2f}, S1 mean p50: {s1_df['p50'].mean():.2f}")
        print(f"  Conclusion: {results['RQ4_H4_1']['conclusion']}")
    
    # Check variance
    f_stat, p_val = stats.levene(s5_df['p50'].dropna(), s1_df['p50'].dropna())
    results['RQ4_H4_2'] = {
        'test': 'Levene test',
        'f_statistic': f_stat,
        'p_value': p_val,
        's5_std': s5_df['p50'].std(),
        's1_std': s1_df['p50'].std(),
        'conclusion': 'H4_2: σ_TTI_S5 > σ_TTI_S1' if p_val < 0.05 else 'H0: No difference in variance',
    }
    print(f"\n  S5 vs S1 variance (H4_2): F={f_stat:.3f}, p={p_val:.4f}")
    print(f"  S5 std p50: {s5_df['p50'].std():.2f}, S1 std p50: {s1_df['p50'].std():.2f}")
    print(f"  Conclusion: {results['RQ4_H4_2']['conclusion']}")
    
    # Issue 3: Throughput and message sizes
    print("\n" + "="*80)
    print("Issue 3: Throughput and Message Size Analysis")
    print("="*80)
    
    throughput_stats = df.groupby('backend')['throughput_events_per_sec'].agg(['mean', 'std', 'min', 'max'])
    print("\n  Throughput by Backend:")
    print(throughput_stats.to_string())
    
    msg_size_stats = df.groupby('backend')['avg_msg_size_bytes'].agg(['mean', 'std', 'min', 'max'])
    print("\n  Average Message Size by Backend:")
    print(msg_size_stats.to_string())
    
    # Convert to simple dict for serialization
    throughput_dict = {}
    for backend in throughput_stats.index:
        throughput_dict[backend] = {
            'mean': throughput_stats.loc[backend, 'mean'],
            'std': throughput_stats.loc[backend, 'std'],
            'min': throughput_stats.loc[backend, 'min'],
            'max': throughput_stats.loc[backend, 'max'],
        }
    
    msg_size_dict = {}
    for backend in msg_size_stats.index:
        msg_size_dict[backend] = {
            'mean': msg_size_stats.loc[backend, 'mean'],
            'std': msg_size_stats.loc[backend, 'std'],
            'min': msg_size_stats.loc[backend, 'min'],
            'max': msg_size_stats.loc[backend, 'max'],
        }
    
    results['Issue3'] = {
        'throughput': throughput_dict,
        'message_size': msg_size_dict,
    }
    
    # Actionability metrics (Issue 5)
    print("\n" + "="*80)
    print("Issue 5: Actionability Metrics")
    print("="*80)
    
    actionability_stats = df.groupby('backend')[['pct_under_100ms', 'pct_under_500ms', 'pct_under_1s', 'pct_under_5s']].mean()
    print("\n  Actionability by Backend (% of events under threshold):")
    print(actionability_stats.to_string())
    
    # Convert to simple dict
    actionability_dict = {}
    for backend in actionability_stats.index:
        actionability_dict[backend] = {
            'pct_under_100ms': actionability_stats.loc[backend, 'pct_under_100ms'],
            'pct_under_500ms': actionability_stats.loc[backend, 'pct_under_500ms'],
            'pct_under_1s': actionability_stats.loc[backend, 'pct_under_1s'],
            'pct_under_5s': actionability_stats.loc[backend, 'pct_under_5s'],
        }
    
    results['Issue5'] = {
        'actionability': actionability_dict,
    }
    
    return results


def generate_graphs(df, output_dir):
    """Generate all graphs for the analysis."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("\n" + "="*80)
    print("Generating Graphs")
    print("="*80)
    
    # Graph 1: TTI p50 Distribution by Backend and Scenario (Boxplot)
    print("  1. backend_scenario_boxplot.png")
    plt.figure(figsize=(12, 8))
    sns.boxplot(
        data=df, 
        x='scenario_name', 
        y='p50', 
        hue='backend',
        palette=COLORS,
        showfliers=False
    )
    plt.title('TTI p50 Distribution by Scenario and Backend')
    plt.ylabel('TTI p50 (ms)')
    plt.xlabel('Scenario')
    plt.xticks(rotation=45, ha='right')
    plt.legend(title='Backend')
    plt.tight_layout()
    plt.savefig(output_dir / 'backend_scenario_boxplot.png')
    plt.close()
    
    # Graph 2: TTI p50 vs Concurrency Level
    print("  2. tti_concurrency_scaling.png")
    plt.figure(figsize=(10, 6))
    sns.lineplot(
        data=df, 
        x='n', 
        y='p50', 
        hue='backend',
        style='backend',
        markers=True,
        palette=COLORS,
        errorbar=('ci', 95)
    )
    plt.title('TTI p50 vs Concurrency Level N')
    plt.ylabel('TTI p50 (ms)')
    plt.xlabel('Concurrency Level (N)')
    plt.legend(title='Backend')
    plt.tight_layout()
    plt.savefig(output_dir / 'tti_concurrency_scaling.png')
    plt.close()
    
    # Graph 3: Match Rate by Configuration
    print("  3. match_rate_bars.png")
    plt.figure(figsize=(12, 6))
    sns.barplot(
        data=df, 
        x='scenario_name', 
        y='match_rate_pct', 
        hue='backend',
        palette=COLORS,
        ci='sd'
    )
    plt.title('Match Rate by Scenario and Backend')
    plt.ylabel('Match Rate (%)')
    plt.xlabel('Scenario')
    plt.ylim(99, 100)
    plt.xticks(rotation=45, ha='right')
    plt.legend(title='Backend')
    plt.tight_layout()
    plt.savefig(output_dir / 'match_rate_bars.png')
    plt.close()
    
    # Graph 4: TTI p50, p95, p99 by Backend
    print("  4. tti_percentiles_backend.png")
    plt.figure(figsize=(10, 6))
    percentiles = ['p50', 'p95', 'p99']
    percentile_data = df[['backend'] + percentiles].melt(id_vars=['backend'], value_vars=percentiles, var_name='percentile', value_name='tti')
    sns.barplot(
        data=percentile_data, 
        x='percentile', 
        y='tti', 
        hue='backend',
        palette=COLORS,
        ci='sd'
    )
    plt.title('TTI Percentiles by Backend')
    plt.ylabel('TTI (ms)')
    plt.xlabel('Percentile')
    plt.legend(title='Backend')
    plt.tight_layout()
    plt.savefig(output_dir / 'tti_percentiles_backend.png')
    plt.close()
    
    # Graph 5: Throughput Comparison
    print("  5. throughput_comparison.png")
    plt.figure(figsize=(10, 6))
    sns.boxplot(
        data=df, 
        x='backend', 
        y='throughput_events_per_sec',
        palette=COLORS,
        showfliers=False
    )
    plt.title('Throughput Comparison: Kafka vs Redis')
    plt.ylabel('Throughput (events/sec)')
    plt.xlabel('Backend')
    plt.tight_layout()
    plt.savefig(output_dir / 'throughput_comparison.png')
    plt.close()
    
    # Graph 6: Actionability Metrics
    print("  6. actionability_metrics.png")
    plt.figure(figsize=(12, 6))
    actionability_df = df.melt(
        id_vars=['backend'],
        value_vars=['pct_under_100ms', 'pct_under_500ms', 'pct_under_1s', 'pct_under_5s'],
        var_name='threshold',
        value_name='percentage'
    )
    actionability_df['threshold'] = actionability_df['threshold'].str.replace('pct_under_', '').str.upper()
    sns.barplot(
        data=actionability_df, 
        x='threshold', 
        y='percentage', 
        hue='backend',
        palette=COLORS
    )
    plt.title('Actionability: % Events Under Latency Thresholds')
    plt.ylabel('Percentage (%)')
    plt.xlabel('Threshold')
    plt.legend(title='Backend')
    plt.tight_layout()
    plt.savefig(output_dir / 'actionability_metrics.png')
    plt.close()
    
    # Graph 7: Config Comparison (Single vs Cluster)
    print("  7. config_comparison.png")
    plt.figure(figsize=(10, 6))
    sns.barplot(
        data=df, 
        x='config', 
        y='p50', 
        hue='backend',
        palette=COLORS,
        ci='sd'
    )
    plt.title('TTI p50: Single vs Cluster Configuration')
    plt.ylabel('TTI p50 (ms)')
    plt.xlabel('Configuration')
    plt.legend(title='Backend')
    plt.tight_layout()
    plt.savefig(output_dir / 'config_comparison.png')
    plt.close()
    
    # Graph 8: Message Size Comparison
    print("  8. message_size_comparison.png")
    plt.figure(figsize=(10, 6))
    sns.boxplot(
        data=df, 
        x='backend', 
        y='avg_msg_size_bytes',
        palette=COLORS,
        showfliers=False
    )
    plt.title('Average Message Size: Kafka vs Redis')
    plt.ylabel('Average Message Size (bytes)')
    plt.xlabel('Backend')
    plt.tight_layout()
    plt.savefig(output_dir / 'message_size_comparison.png')
    plt.close()
    
    print(f"\n  Generated {len(list(output_dir.glob('*.png')))} graphs in {output_dir}")


def generate_summary_tables(df, output_dir):
    """Generate summary tables in CSV and markdown formats."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("\n" + "="*80)
    print("Generating Summary Tables")
    print("="*80)
    
    # Table 1: Overall Performance Comparison
    print("  1. overall_performance_summary.csv")
    overall_stats = df.groupby('backend').agg({
        'p50': ['mean', 'std', 'min', 'max'],
        'p95': ['mean', 'std'],
        'p99': ['mean', 'std'],
        'mean': ['mean', 'std'],
        'match_rate_pct': ['mean', 'min'],
        'throughput_events_per_sec': ['mean', 'std'],
        'avg_msg_size_bytes': ['mean', 'std'],
    }).round(2)
    overall_stats.to_csv(output_dir / 'overall_performance_summary.csv')
    
    # Table 2: By Scenario
    print("  2. scenario_performance_summary.csv")
    scenario_stats = df.groupby(['backend', 'scenario_name']).agg({
        'p50': ['mean', 'std'],
        'p95': ['mean', 'std'],
        'p99': ['mean', 'std'],
        'match_rate_pct': ['mean', 'min'],
        'throughput_events_per_sec': 'mean',
    }).round(2)
    scenario_stats.to_csv(output_dir / 'scenario_performance_summary.csv')
    
    # Table 3: By Concurrency Level
    print("  3. concurrency_performance_summary.csv")
    concurrency_stats = df.groupby(['backend', 'n']).agg({
        'p50': ['mean', 'std'],
        'p95': ['mean', 'std'],
        'match_rate_pct': 'mean',
        'throughput_events_per_sec': 'mean',
    }).round(2)
    concurrency_stats.to_csv(output_dir / 'concurrency_performance_summary.csv')
    
    # Table 4: Actionability Summary
    print("  4. actionability_summary.csv")
    actionability_stats = df.groupby('backend').agg({
        'pct_under_100ms': ['mean', 'std'],
        'pct_under_500ms': ['mean', 'std'],
        'pct_under_1s': ['mean', 'std'],
        'pct_under_5s': ['mean', 'std'],
    }).round(2)
    actionability_stats.to_csv(output_dir / 'actionability_summary.csv')
    
    # Table 5: Configuration Comparison (Single vs Cluster)
    print("  5. config_comparison_summary.csv")
    config_stats = df.groupby(['backend', 'config']).agg({
        'p50': ['mean', 'std'],
        'p95': ['mean', 'std'],
        'match_rate_pct': 'mean',
        'throughput_events_per_sec': 'mean',
    }).round(2)
    config_stats.to_csv(output_dir / 'config_comparison_summary.csv')
    
    print(f"\n  Generated {len(list(output_dir.glob('*.csv')))} summary tables in {output_dir}")


def save_results(hypothesis_results, output_dir):
    """Save hypothesis test results to JSON and markdown."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("\n" + "="*80)
    print("Saving Hypothesis Test Results")
    print("="*80)
    
    # Save to JSON
    with open(output_dir / 'hypothesis_tests_results.json', 'w') as f:
        json.dump(hypothesis_results, f, indent=2, default=str)
    print(f"  1. hypothesis_tests_results.json")
    
    # Save to markdown
    with open(output_dir / 'HYPOTHESIS_RESULTS.md', 'w') as f:
        f.write("# Hypothesis Test Results\n\n")
        f.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("## RQ1: Architecture Impact\n\n")
        rq1 = hypothesis_results.get('RQ1', {})
        f.write(f"- **Test:** {rq1.get('test', 'N/A')}\n")
        def fmt(val, spec):
            return f"{val:{spec}}" if isinstance(val, (int, float)) else str(val)
        
        f.write(f"- **U Statistic:** {fmt(rq1.get('u_statistic', 'N/A'), '.2f')}\n")
        f.write(f"- **p-value:** {fmt(rq1.get('p_value', 'N/A'), '.4f')}\n")
        f.write(f"- **Cohen's d:** {fmt(rq1.get('cohen_d', 'N/A'), '.3f')}\n")
        f.write(f"- **Kafka mean p50:** {fmt(rq1.get('kafka_mean_p50', 'N/A'), '.2f')} ms\n")
        f.write(f"- **Redis mean p50:** {fmt(rq1.get('redis_mean_p50', 'N/A'), '.2f')} ms\n")
        f.write(f"- **Improvement:** {fmt(rq1.get('improvement_pct', 'N/A'), '.1f')}%\n")
        f.write(f"- **Conclusion:** {rq1.get('conclusion', 'N/A')}\n\n")
        
        f.write("## RQ2: Concurrency Scaling\n\n")
        rq2 = hypothesis_results.get('RQ2', {})
        f.write(f"- **Test:** {rq2.get('test', 'N/A')}\n")
        f.write(f"- **H Statistic:** {fmt(rq2.get('h_statistic', 'N/A'), '.2f')}\n")
        f.write(f"- **p-value:** {fmt(rq2.get('p_value', 'N/A'), '.4f')}\n")
        f.write(f"- **Conclusion:** {rq2.get('conclusion', 'N/A')}\n")
        if 'pairwise' in rq2:
            f.write("\n  **Pairwise Comparisons:**\n")
            for comp in rq2['pairwise']:
                f.write(f"  - N={comp['n1']} vs N={comp['n2']}: U={fmt(comp['u_stat'], '.2f')}, p={fmt(comp['p_value'], '.4f')}, significant={comp['significant']}\n")
        f.write("\n")
        
        f.write("## RQ3: Latency-Consistency Trade-off\n\n")
        rq3 = hypothesis_results.get('RQ3', {})
        f.write(f"- **Mean Match Rate:** {fmt(rq3.get('mean_match_rate', 'N/A'), '.2f')}%\n")
        f.write(f"- **Min Match Rate:** {fmt(rq3.get('min_match_rate', 'N/A'), '.2f')}%\n")
        f.write(f"- **All 100%:** {rq3.get('match_rate_all_100', 'N/A')}\n")
        f.write(f"- **All >99.9%:** {rq3.get('match_rate_all_above_999', 'N/A')}\n")
        f.write(f"- **Conclusion:** {rq3.get('conclusion_match', 'N/A')}\n\n")
        
        f.write("## RQ4: Sports-Specific Performance\n\n")
        if 'RQ4_H4_1' in hypothesis_results:
            rq4_1 = hypothesis_results['RQ4_H4_1']
            f.write(f"- **H4_1 Test:** {rq4_1.get('test', 'N/A')}\n")
            f.write(f"- **t Statistic:** {fmt(rq4_1.get('t_statistic', 'N/A'), '.3f')}\n")
            f.write(f"- **p-value:** {fmt(rq4_1.get('p_value', 'N/A'), '.4f')}\n")
            f.write(f"- **Conclusion:** {rq4_1.get('conclusion', 'N/A')}\n\n")
        if 'RQ4_H4_2' in hypothesis_results:
            rq4_2 = hypothesis_results['RQ4_H4_2']
            f.write(f"- **H4_2 Test:** {rq4_2.get('test', 'N/A')}\n")
            f.write(f"- **F Statistic:** {fmt(rq4_2.get('f_statistic', 'N/A'), '.3f')}\n")
            f.write(f"- **p-value:** {fmt(rq4_2.get('p_value', 'N/A'), '.4f')}\n")
            f.write(f"- **Conclusion:** {rq4_2.get('conclusion', 'N/A')}\n\n")
        
        f.write("## Issue 3: Throughput and Message Sizes\n\n")
        issue3 = hypothesis_results.get('Issue3', {})
        if 'throughput' in issue3:
            f.write("  **Throughput (events/sec):**\n")
            for backend, stats in issue3['throughput'].items():
                f.write(f"  - {backend}: mean={stats['mean']:.2f}, std={stats['std']:.2f}, min={stats['min']:.2f}, max={stats['max']:.2f}\n")
        if 'message_size' in issue3:
            f.write("\n  **Message Size (bytes):**\n")
            for backend, stats in issue3['message_size'].items():
                f.write(f"  - {backend}: mean={stats['mean']:.2f}, std={stats['std']:.2f}, min={stats['min']:.2f}, max={stats['max']:.2f}\n")
        f.write("\n")
        
        f.write("## Issue 5: Actionability Metrics\n\n")
        issue5 = hypothesis_results.get('Issue5', {})
        if 'actionability' in issue5:
            f.write("  **% Events Under Threshold:**\n")
            for backend, metrics in issue5['actionability'].items():
                f.write(f"  - {backend}:\n")
                for threshold, pct in metrics.items():
                    f.write(f"    - {threshold}: {pct:.2f}%\n")
    
    print(f"  2. HYPOTHESIS_RESULTS.md")


def main():
    parser = argparse.ArgumentParser(
        description='Analyze 120 multi-broker runs (batches 1-3)'
    )
    parser.add_argument(
        '--output-dir', 
        type=str, 
        default='docs/results/batches_1_2_3_analysis',
        help='Output directory for results'
    )
    parser.add_argument(
        '--batch-pattern',
        type=str,
        default='batch[123]_*',
        help='Glob pattern for batch directories'
    )
    args = parser.parse_args()
    
    print("="*80)
    print("ANALYSIS OF 120 MULTI-BROKER RUNS (BATCHES 1-3)")
    print("="*80)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Step 1: Load all run data
    print("Step 1: Loading run data...")
    df = load_all_batch_runs(args.batch_pattern)
    print(f"Loaded {len(df)} runs")
    print()
    
    if len(df) == 0:
        print("ERROR: No runs loaded. Check batch pattern.")
        sys.exit(1)
    
    # Step 2: Run hypothesis tests
    print("Step 2: Running hypothesis tests...")
    hypothesis_results = run_hypothesis_tests(df)
    print()
    
    # Step 3: Generate graphs
    print("Step 3: Generating graphs...")
    generate_graphs(df, args.output_dir)
    print()
    
    # Step 4: Generate summary tables
    print("Step 4: Generating summary tables...")
    generate_summary_tables(df, args.output_dir)
    print()
    
    # Step 5: Save results
    print("Step 5: Saving hypothesis test results...")
    save_results(hypothesis_results, args.output_dir)
    print()
    
    # Step 6: Print summary
    print("="*80)
    print("ANALYSIS COMPLETE")
    print("="*80)
    print(f"Output directory: {args.output_dir}")
    print(f"Runs analyzed: {len(df)}")
    print(f"Backends: {df['backend'].unique().tolist()}")
    print(f"Scenarios: {df['scenario'].unique().tolist()}")
    print(f"Concurrency levels: {sorted(df['n'].unique())}")
    print(f"Configs: {df['config'].unique().tolist()}")
    print()
    
    # Print key results
    print("KEY RESULTS:")
    print(f"  - Kafka mean p50: {df[df['backend']=='kafka']['p50'].mean():.2f} ms")
    print(f"  - Redis mean p50: {df[df['backend']=='redis']['p50'].mean():.2f} ms")
    print(f"  - Improvement: {((df[df['backend']=='kafka']['p50'].mean() - df[df['backend']=='redis']['p50'].mean()) / df[df['backend']=='kafka']['p50'].mean()) * 100:.1f}%")
    print(f"  - Mean match rate: {df['match_rate_pct'].mean():.2f}%")
    print(f"  - Kafka mean throughput: {df[df['backend']=='kafka']['throughput_events_per_sec'].mean():.2f} events/sec")
    print(f"  - Redis mean throughput: {df[df['backend']=='redis']['throughput_events_per_sec'].mean():.2f} events/sec")


if __name__ == '__main__':
    main()
