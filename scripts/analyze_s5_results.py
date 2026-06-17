#!/usr/bin/env python3
"""
S5 Resource Analysis - Quality Metrics
Analyzes S5 runs for computational resource usage and quality metrics.

Outputs:
- docs/results/s5_quality_summary.md
- docs/results/s5_quality_metrics.csv
"""
import json
import pandas as pd
import numpy as np
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns

# Ensure output directories exist
Path("docs/results/s5_figures").mkdir(parents=True, exist_ok=True)

# Set plotting style
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (12, 7)
plt.rcParams['font.size'] = 12
plt.rcParams['savefig.dpi'] = 300
plt.rcParams['savefig.bbox'] = 'tight'


def parse_s5_run_id(run_id):
    """Parse S5 run ID: s5_<scenario>_<config>_<backend>_rep<N>_<timestamp>
    Config names may contain underscores (e.g., 'high_speedup').
    """
    parts = run_id.split('_')
    # parts: [s5, scenario, ...config parts..., backend, repN, date, time]
    # Find the index of 'rep' to locate backend
    rep_index = None
    for i, part in enumerate(parts):
        if part.startswith('rep'):
            rep_index = i
            break
    
    if rep_index is None or rep_index < 4:
        # Fallback: use fixed positions
        return {
            'scenario': parts[1] if len(parts) > 1 else '',
            'config': parts[2] if len(parts) > 2 else '',
            'backend': parts[3] if len(parts) > 3 else '',
            'rep': parts[4] if len(parts) > 4 else '',
            'timestamp': '_'.join(parts[5:]) if len(parts) > 5 else ''
        }
    
    # Backend is the part before rep
    backend = parts[rep_index - 1]
    # Config is everything between scenario and backend
    config = '_'.join(parts[2:rep_index - 1])
    scenario = parts[1]
    timestamp = '_'.join(parts[rep_index + 1:])
    
    return {
        'scenario': scenario,
        'config': config,
        'backend': backend,
        'rep': parts[rep_index],
        'timestamp': timestamp
    }


def extract_config_params(config_name):
    """Map config name to parameters."""
    config_map = {
        'baseline': {'speedup': 120, 'corrections_every_k': 50, 'correction_delay_s': 2.0},
        'low_speedup': {'speedup': 60, 'corrections_every_k': 50, 'correction_delay_s': 2.0},
        'high_speedup': {'speedup': 240, 'corrections_every_k': 50, 'correction_delay_s': 2.0},
        'high_frequency': {'speedup': 120, 'corrections_every_k': 10, 'correction_delay_s': 2.0},
        'low_frequency': {'speedup': 120, 'corrections_every_k': 100, 'correction_delay_s': 2.0},
        'long_delay': {'speedup': 120, 'corrections_every_k': 50, 'correction_delay_s': 5.0},
        'fast_corrections': {'speedup': 120, 'corrections_every_k': 10, 'correction_delay_s': 0.5},
    }
    return config_map.get(config_name, {})


def load_s5_run(run_dir):
    """Load metrics from a single S5 run directory."""
    run_id = run_dir.name
    parsed = parse_s5_run_id(run_id)
    
    # Load TTI summary
    tti_path = run_dir / "tti_summary.json"
    tti_data = {}
    if tti_path.exists():
        try:
            with open(tti_path, encoding='utf-8-sig') as f:
                tti_data = json.load(f)
        except Exception as e:
            print(f"Warning: Could not load TTI from {run_dir}: {e}")
    
    # Load meta
    meta_path = run_dir / "meta.json"
    meta = {}
    if meta_path.exists():
        try:
            with open(meta_path, encoding='utf-8-sig') as f:
                meta = json.load(f)
        except Exception:
            pass
    
    # Count producer/consumer events
    n_producer = 0
    n_consumer = 0
    for fname, target_var in [("producer.csv", "n_producer"), ("consumer.csv", "n_consumer")]:
        fpath = run_dir / fname
        if fpath.exists():
            try:
                with open(fpath, encoding='utf-8-sig') as f:
                    n_lines = sum(1 for _ in f) - 1  # Exclude header
                if target_var == "n_producer":
                    n_producer = n_lines
                elif target_var == "n_consumer":
                    n_consumer = n_lines
            except Exception:
                pass
    
    # Load resource metrics if available
    resource_path = run_dir / "resource_summary.json"
    resource_data = {}
    if resource_path.exists():
        try:
            with open(resource_path, encoding='utf-8-sig') as f:
                resource_data = json.load(f)
        except Exception:
            pass
    
    metrics = {
        'run_id': run_id,
        'scenario': parsed['scenario'],
        'config': parsed['config'],
        'backend': parsed['backend'],
        'rep': parsed['rep'],
        'n_producer_events': n_producer,
        'n_consumer_events': n_consumer,
    }
    
    # Add config parameters
    config_params = extract_config_params(parsed['config'])
    for key, value in config_params.items():
        metrics[key] = value
    
    # Add TTI metrics
    if 'tti_ms' in tti_data and isinstance(tti_data['tti_ms'], dict):
        for key in ['p50', 'p95', 'p99', 'max', 'mean', 'std', 'min', 'count']:
            if key in tti_data['tti_ms']:
                metrics[f'tti_{key}'] = tti_data['tti_ms'][key]
    else:
        # Try flat structure
        for key in ['p50', 'p95', 'p99', 'max', 'mean', 'std', 'min', 'count']:
            flat_key = f'tti_ms_{key}'
            if flat_key in tti_data:
                metrics[f'tti_{key}'] = tti_data[flat_key]
    
    # Add transport metrics if available
    if 'transport_ms' in tti_data and isinstance(tti_data['transport_ms'], dict):
        for key in ['p50', 'p95', 'p99', 'max', 'mean']:
            if key in tti_data['transport_ms']:
                metrics[f'transport_{key}'] = tti_data['transport_ms'][key]
    else:
        # Try flat structure
        for key in ['p50', 'p95', 'p99', 'max', 'mean']:
            flat_key = f'transport_ms_{key}'
            if flat_key in tti_data:
                metrics[f'transport_{key}'] = tti_data[flat_key]
    
    # Add resource metrics
    for key, value in resource_data.items():
        metrics[f'resource_{key}'] = value
    
    # Add matched/consume counts
    for key in ['n_produced', 'n_consumed', 'n_matched']:
        if key in tti_data:
            metrics[key] = tti_data[key]
    
    return metrics


def compute_quality_metrics(df: pd.DataFrame):
    """Compute quality metrics for S5 runs."""
    print("Computing quality metrics...")
    
    # Group by backend and config
    if len(df) == 0 or 'backend' not in df.columns or 'config' not in df.columns:
        return pd.DataFrame()
    
    grouped = df.groupby(['backend', 'config'])
    
    results = []
    for (backend, config), group in grouped:
        result = {
            'backend': backend,
            'config': config,
            'count': len(group),
            'avg_tti_p50': group['tti_p50'].mean() if 'tti_p50' in group.columns else np.nan,
            'avg_tti_p95': group['tti_p95'].mean() if 'tti_p95' in group.columns else np.nan,
            'avg_tti_mean': group['tti_mean'].mean() if 'tti_mean' in group.columns else np.nan,
            'total_producer_events': group['n_producer_events'].sum() if 'n_producer_events' in group.columns else np.nan,
            'total_consumer_events': group['n_consumer_events'].sum() if 'n_consumer_events' in group.columns else np.nan,
            'match_rate': group['n_matched'].mean() / group['n_produced'].mean() if 'n_matched' in group.columns and 'n_produced' in group.columns else np.nan,
        }
        
        # Add config parameters if available
        for param in ['speedup', 'corrections_every_k', 'correction_delay_s']:
            if param in group.columns:
                result[param] = group[param].mean()
        
        # Add resource metrics if available
        numeric_resource_cols = [c for c in df.columns if c.startswith('resource_') and pd.api.types.is_numeric_dtype(df[c])]
        for col in numeric_resource_cols:
            if col in group.columns:
                metric_name = col.replace('resource_', '')
                result[f'avg_{metric_name}'] = group[col].mean()
        
        results.append(result)
    
    return pd.DataFrame(results)


def generate_quality_plots(df: pd.DataFrame, quality_df: pd.DataFrame):
    """Generate quality comparison plots."""
    print("Generating quality plots...")
    
    backends = df['backend'].unique()
    configs = df['config'].unique()
    
    # Plot 1: TTI p50 by backend and config
    if 'tti_p50' in df.columns:
        plt.figure()
        sns.barplot(data=df, x='config', y='tti_p50', hue='backend',
                    palette={'kafka': 'royalblue', 'redis': 'indianred'})
        plt.title('TTI p50 by Configuration and Backend')
        plt.xlabel('Configuration')
        plt.ylabel('TTI p50 (ms)')
        plt.legend(title='Backend')
        plt.tight_layout()
        plt.savefig('docs/results/s5_figures/tti_p50_by_config_backend.png')
        plt.close()
        print("  Saved: docs/results/s5_figures/tti_p50_by_config_backend.png")
    
    # Plot 2: TTI p95 by backend and config
    if 'tti_p95' in df.columns:
        plt.figure()
        sns.barplot(data=df, x='config', y='tti_p95', hue='backend',
                    palette={'kafka': 'royalblue', 'redis': 'indianred'})
        plt.title('TTI p95 by Configuration and Backend')
        plt.xlabel('Configuration')
        plt.ylabel('TTI p95 (ms)')
        plt.legend(title='Backend')
        plt.tight_layout()
        plt.savefig('docs/results/s5_figures/tti_p95_by_config_backend.png')
        plt.close()
        print("  Saved: docs/results/s5_figures/tti_p95_by_config_backend.png")
    
    # Plot 3: Producer/Consumer event counts
    if 'n_producer_events' in df.columns and 'n_consumer_events' in df.columns:
        plt.figure()
        event_df = df.melt(id_vars=['run_id', 'backend', 'config'],
                           value_vars=['n_producer_events', 'n_consumer_events'],
                           var_name='event_type', value_name='count')
        sns.barplot(data=event_df, x='config', y='count', hue='backend',
                    palette={'kafka': 'royalblue', 'redis': 'indianred'})
        plt.title('Event Counts by Configuration and Backend')
        plt.xlabel('Configuration')
        plt.ylabel('Count')
        plt.legend(title='Backend')
        plt.tight_layout()
        plt.savefig('docs/results/s5_figures/event_counts_by_config_backend.png')
        plt.close()
        print("  Saved: docs/results/s5_figures/event_counts_by_config_backend.png")


def generate_summary_markdown(df: pd.DataFrame, quality_df: pd.DataFrame):
    """Generate S5 quality analysis summary."""
    print("Generating summary markdown...")
    
    with open("docs/results/s5_quality_summary.md", 'w') as f:
        f.write("# S5 Resource Analysis - Quality Metrics\n\n")
        f.write("**Date:** 2026-06-12\n\n")
        f.write("**Objective:** Analyze computational resource usage and quality metrics for S5 parameter sweep\n\n")
        
        # Overview
        f.write("## Overview\n\n")
        f.write(f"- **Total Runs:** {len(df)}\n")
        f.write(f"- **Scenarios:** {df['scenario'].nunique()} ({', '.join(sorted(df['scenario'].unique()))})\n")
        f.write(f"- **Configurations:** {df['config'].nunique()} ({', '.join(sorted(df['config'].unique()))})\n")
        f.write(f"- **Backends:** {df['backend'].nunique()} ({', '.join(sorted(df['backend'].unique()))})\n\n")
        
        # Parameter space
        f.write("## Parameter Space\n\n")
        f.write("| Parameter | Values Tested |\n")
        f.write("|-----------|----------------|\n")
        if 'speedup' in df.columns:
            f.write(f"| speedup | {', '.join(map(str, sorted(df['speedup'].unique())))}|\n")
        if 'corrections_every_k' in df.columns:
            f.write(f"| corrections_every_k | {', '.join(map(str, sorted(df['corrections_every_k'].unique())))}|\n")
        if 'correction_delay_s' in df.columns:
            f.write(f"| correction_delay_s | {', '.join(map(str, sorted(df['correction_delay_s'].unique())))}|\n")
        f.write("\n")
        
        # Quality Metrics
        f.write("## Quality Metrics\n\n")
        f.write("### Average TTI Metrics\n\n")
        f.write("| Backend | Config | Speedup | Count | TTI p50 | TTI p95 | TTI Mean |\n")
        f.write("|---------|--------|---------|-------|---------|---------|----------|\n")
        
        for _, row in quality_df.iterrows():
            f.write(f"| {row['backend']} | {row['config']} | {int(row.get('speedup', 0))} | {int(row['count'])} | "
                  f"{row.get('avg_tti_p50', 0):.2f} | {row.get('avg_tti_p95', 0):.2f} | {row.get('avg_tti_mean', 0):.2f} |\n")
        f.write("\n")
        
        # Resource Metrics (if available)
        # Resource columns are named avg_<resource_metric> (e.g., avg_kafka_avg_cpu)
        resource_cols = [c for c in quality_df.columns if c.startswith('avg_') and not c.startswith('avg_tti_') and not c.startswith('avg_transport_')]
        if resource_cols:
            f.write("### Resource Metrics\n\n")
            col_labels = [c.replace('avg_', '').replace('_', ' ').title() for c in resource_cols]
            f.write("| Backend | Config | " + " | ".join(col_labels) + " |\n")
            f.write("|---------|--------|" + " | " * len(resource_cols) + "|\n")
            for _, row in quality_df.iterrows():
                values = [row.get(c, 0) for c in resource_cols]
                f.write(f"| {row['backend']} | {row['config']} | " + " | ".join([f"{v:.2f}" for v in values]) + " |\n")
            f.write("\n")
        
        # Figures
        f.write("## Figures\n\n")
        f.write("Generated figures in `docs/results/s5_figures/`:\n")
        f.write("- `tti_p50_by_config_backend.png` - TTI p50 comparison\n")
        f.write("- `tti_p95_by_config_backend.png` - TTI p95 comparison\n")
        f.write("- `event_counts_by_config_backend.png` - Event count comparison\n\n")


def main():
    """Main analysis pipeline."""
    print("=" * 80)
    print("S5 RESOURCE ANALYSIS - QUALITY METRICS")
    print("=" * 80)
    
    # Find all S5 run directories
    runs_dir = Path("runs")
    s5_dirs = sorted([d for d in runs_dir.iterdir() if d.is_dir() and d.name.startswith('s5_')])
    
    print(f"\nFound {len(s5_dirs)} S5 run directories")
    
    if not s5_dirs:
        print("ERROR: No S5 runs found. Run S5 trials first.")
        return 1
    
    # Load all runs
    all_metrics = []
    for run_dir in s5_dirs:
        try:
            metrics = load_s5_run(run_dir)
            all_metrics.append(metrics)
            print(f"  Loaded: {run_dir.name}")
        except Exception as e:
            print(f"  ERROR loading {run_dir.name}: {e}")
    
    if not all_metrics:
        print("ERROR: No valid S5 runs loaded.")
        return 1
    
    # Create DataFrame
    df = pd.DataFrame(all_metrics)
    
    print(f"\nLoaded {len(df)} valid S5 runs")
    print(f"Backends: {sorted(df['backend'].unique())}")
    print(f"Configs: {sorted(df['config'].unique())}")
    print(f"Scenarios: {sorted(df['scenario'].unique())}")
    
    # Save raw metrics
    output_csv = "data/processed/results/paper_s5_quality_metrics.csv"
    df.to_csv(output_csv, index=False)
    print(f"\nSaved raw metrics: {output_csv}")
    
    # Compute quality metrics
    quality_df = compute_quality_metrics(df)
    quality_csv = "data/processed/results/paper_s5_quality_summary.csv"
    quality_df.to_csv(quality_csv, index=False)
    print(f"Saved quality summary: {quality_csv}")
    
    # Generate outputs
    generate_quality_plots(df, quality_df)
    generate_summary_markdown(df, quality_df)
    
    print("\n" + "=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)
    print("Outputs generated:")
    print(f"  - {output_csv}")
    print(f"  - {quality_csv}")
    print("  - docs/results/s5_quality_summary.md")
    print("  - docs/results/s5_figures/*.png")
    print("=" * 80)
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
