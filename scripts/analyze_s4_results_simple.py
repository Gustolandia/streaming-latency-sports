#!/usr/bin/env python3
"""
Simple S4 Parameter Sweep Analysis Script
Generates figures and tables for manuscript.
"""
import json
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
import argparse


# Set up plotting
plt.rcParams['figure.figsize'] = (10, 6)
plt.rcParams['figure.dpi'] = 300
plt.rcParams['savefig.dpi'] = 300
sns.set_style("whitegrid")


def load_s4_data(csv_path="data/processed/results/paper_s4_parameter_sweep.csv"):
    """Load S4 metrics CSV."""
    df = pd.read_csv(csv_path)
    
    # Ensure we have the run column (might be named differently)
    if 'run' not in df.columns:
        # Try to find the run_id column
        for col in df.columns:
            if 'run' in col.lower() or 'id' in col.lower():
                df = df.rename(columns={col: 'run'})
                break
    
    # Extract config info from run_id if not already present
    if 'scenario' not in df.columns and 'run' in df.columns:
        # Parse run_id: s4_<scenario>_<config>_<backend>_rep<N>_<date>
        def extract_info(run_id):
            parts = run_id.split("_")
            valid_backends = ["kafka", "redis"]
            backend_idx = None
            for i, part in enumerate(parts):
                if part in valid_backends:
                    backend_idx = i
                    break
            
            if backend_idx is None or len(parts) < 4:
                return pd.Series({'scenario': None, 'config': None, 'backend': None})
            
            scenario = parts[1] if len(parts) > 1 else None
            config = "_".join(parts[2:backend_idx]) if backend_idx > 2 else None
            backend = parts[backend_idx] if backend_idx else None
            return pd.Series({'scenario': scenario, 'config': config, 'backend': backend})
        
        info_df = df['run'].apply(extract_info)
        df = pd.concat([df, info_df], axis=1)
    
    # Map config to parameters if not present
    config_map = {
        "baseline": {"speedup": 120, "corrections_every_k": 50, "correction_delay_s": 2.0},
        "low_speedup": {"speedup": 60, "corrections_every_k": 50, "correction_delay_s": 2.0},
        "high_speedup": {"speedup": 240, "corrections_every_k": 50, "correction_delay_s": 2.0},
        "high_frequency": {"speedup": 120, "corrections_every_k": 10, "correction_delay_s": 2.0},
        "low_frequency": {"speedup": 120, "corrections_every_k": 100, "correction_delay_s": 2.0},
        "long_delay": {"speedup": 120, "corrections_every_k": 50, "correction_delay_s": 5.0},
        "short_delay": {"speedup": 120, "corrections_every_k": 50, "correction_delay_s": 0.5},
        "fast_corrections": {"speedup": 120, "corrections_every_k": 10, "correction_delay_s": 0.5},
    }
    
    if 'config' in df.columns:
        for param in ['speedup', 'corrections_every_k', 'correction_delay_s']:
            if param not in df.columns:
                df[param] = df['config'].apply(lambda x: config_map.get(x, {}).get(param, 0))
    
    return df


def create_output_dir(output_dir):
    """Create output directory."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "tables").mkdir(parents=True, exist_ok=True)
    (output_dir / "figures").mkdir(parents=True, exist_ok=True)
    return output_dir


def generate_tables(df, output_dir):
    """Generate summary tables."""
    output_dir = Path(output_dir)
    
    # Table 1: Overall comparison Kafka vs Redis
    # Use n_n_matched or n_tti_values
    matched_col = 'n_n_matched' if 'n_n_matched' in df.columns else ('n_tti_values' if 'n_tti_values' in df.columns else None)
    agg_dict = {
        'tti_p50': ['mean', 'std', 'min', 'max'],
        'tti_p95': ['mean', 'std'],
        'tti_p99': ['mean', 'std'],
        'tti_mean': 'mean',
    }
    if matched_col:
        agg_dict[matched_col] = 'sum'
    backend_stats = df.groupby('backend').agg(agg_dict).round(2)
    
    # Flatten multi-index columns
    backend_stats.columns = [f"{col}_{stat}" for col, stat in backend_stats.columns]
    backend_stats.to_csv(output_dir / "tables" / "s4_backend_comparison.csv")
    print(f"Saved: tables/s4_backend_comparison.csv")
    
    # Table 2: By configuration
    config_agg = {
        'tti_p50': ['mean', 'std'],
        'tti_p95': ['mean', 'std'],
        'tti_mean': 'mean',
    }
    if matched_col:
        config_agg[matched_col] = 'sum'
    config_stats = df.groupby(['config', 'backend']).agg(config_agg).round(2)
    config_stats.columns = [f"{col}_{stat}" for col, stat in config_stats.columns]
    config_stats.to_csv(output_dir / "tables" / "s4_config_comparison.csv")
    print(f"Saved: tables/s4_config_comparison.csv")
    
    # Table 3: Parameter effects
    for param in ['speedup', 'corrections_every_k', 'correction_delay_s']:
        if param in df.columns:
            param_stats = df.groupby([param, 'backend']).agg({
                'tti_p50': ['mean', 'std'],
                'tti_p95': ['mean', 'std'],
            }).round(2)
            param_stats.columns = [f"{col}_{stat}" for col, stat in param_stats.columns]
            param_stats.to_csv(output_dir / "tables" / f"s4_by_{param}.csv")
            print(f"Saved: tables/s4_by_{param}.csv")
    
    # Table 4: Full data
    df.to_csv(output_dir / "tables" / "s4_all_data.csv", index=False)
    print(f"Saved: tables/s4_all_data.csv")


def generate_figures(df, output_dir):
    """Generate analysis figures."""
    output_dir = Path(output_dir) / "figures"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Figure 1: TTI distribution by backend (boxplot)
    plt.figure(figsize=(10, 6))
    sns.boxplot(data=df, x='backend', y='tti_p50', palette={'kafka': 'orange', 'redis': 'blue'})
    plt.title('Median TTI Distribution: Kafka vs Redis (S4 Parameter Sweep)')
    plt.ylabel('Median TTI (ms)')
    plt.xlabel('Backend')
    plt.yscale('log')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_dir / "s4_tti_backend_boxplot.png")
    plt.close()
    print(f"Saved: figures/s4_tti_backend_boxplot.png")
    
    # Figure 2: TTI by configuration
    plt.figure(figsize=(14, 8))
    sns.boxplot(data=df, x='config', y='tti_p50', hue='backend',
                palette={'kafka': 'orange', 'redis': 'blue'})
    plt.title('Median TTI by Configuration')
    plt.ylabel('Median TTI (ms)')
    plt.xlabel('Configuration')
    plt.xticks(rotation=45)
    plt.yscale('log')
    plt.legend(title='Backend')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_dir / "s4_tti_by_config.png")
    plt.close()
    print(f"Saved: figures/s4_tti_by_config.png")
    
    # Figure 3: Parameter impact - speedup
    plt.figure(figsize=(12, 6))
    for backend in df['backend'].unique():
        backend_df = df[df['backend'] == backend]
        speedups = sorted(backend_df['speedup'].unique())
        means = [backend_df[backend_df['speedup'] == s]['tti_p50'].mean() for s in speedups]
        stds = [backend_df[backend_df['speedup'] == s]['tti_p50'].std() for s in speedups]
        plt.errorbar(speedups, means, yerr=stds, label=backend.capitalize(),
                     fmt='o-', capsize=5)
    plt.title('Impact of Speedup Factor on Median TTI')
    plt.xlabel('Speedup Factor')
    plt.ylabel('Median TTI (ms)')
    plt.yscale('log')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_dir / "s4_speedup_impact.png")
    plt.close()
    print(f"Saved: figures/s4_speedup_impact.png")
    
    # Figure 4: Parameter impact - corrections_every_k
    plt.figure(figsize=(12, 6))
    for backend in df['backend'].unique():
        backend_df = df[df['backend'] == backend]
        k_values = sorted(backend_df['corrections_every_k'].unique())
        means = [backend_df[backend_df['corrections_every_k'] == k]['tti_p50'].mean() for k in k_values]
        stds = [backend_df[backend_df['corrections_every_k'] == k]['tti_p50'].std() for k in k_values]
        plt.errorbar(k_values, means, yerr=stds, label=backend.capitalize(),
                     fmt='o-', capsize=5)
    plt.title('Impact of Correction Frequency on Median TTI')
    plt.xlabel('Corrections Every K Events')
    plt.ylabel('Median TTI (ms)')
    plt.yscale('log')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_dir / "s4_correction_freq_impact.png")
    plt.close()
    print(f"Saved: figures/s4_correction_freq_impact.png")
    
    # Figure 5: Parameter impact - correction_delay_s
    plt.figure(figsize=(12, 6))
    for backend in df['backend'].unique():
        backend_df = df[df['backend'] == backend]
        delays = sorted(backend_df['correction_delay_s'].unique())
        means = [backend_df[backend_df['correction_delay_s'] == d]['tti_p50'].mean() for d in delays]
        stds = [backend_df[backend_df['correction_delay_s'] == d]['tti_p50'].std() for d in delays]
        plt.errorbar(delays, means, yerr=stds, label=backend.capitalize(),
                     fmt='o-', capsize=5)
    plt.title('Impact of Correction Delay on Median TTI')
    plt.xlabel('Correction Delay (seconds)')
    plt.ylabel('Median TTI (ms)')
    plt.yscale('log')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_dir / "s4_correction_delay_impact.png")
    plt.close()
    print(f"Saved: figures/s4_correction_delay_impact.png")
    
    # Figure 6: Missed window rates
    missed_cols = [col for col in df.columns if col.startswith('missed_window_')]
    if missed_cols:
        plt.figure(figsize=(12, 6))
        for backend in df['backend'].unique():
            backend_df = df[df['backend'] == backend]
            # Extract window sizes from column names (e.g., missed_window_100ms_rate -> 100)
            windows = []
            for col in missed_cols:
                # Extract number before 'ms'
                parts = col.replace('missed_window_', '').replace('_rate', '').split('ms')
                if parts and parts[0]:
                    try:
                        windows.append(int(parts[0]))
                    except ValueError:
                        pass
            if windows:
                rates = [backend_df[f'missed_window_{w}ms_rate'].mean() for w in windows]
                plt.plot(windows, rates, 'o-', label=backend.capitalize())
        plt.title('Missed Window Rates by Threshold')
        plt.xlabel('Actionability Window (ms)')
        plt.ylabel('Missed Window Rate')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(output_dir / "s4_missed_window_rates.png")
        plt.close()
        print(f"Saved: figures/s4_missed_window_rates.png")


def generate_report(df, output_dir):
    """Generate markdown report."""
    output_dir = Path(output_dir)
    report_path = output_dir / "s4_analysis_report.md"
    
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("# S4 Parameter Sweep Analysis Report\n\n")
        f.write(f"**Date:** {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        # Overview
        f.write("## Overview\n\n")
        f.write(f"- **Total Runs:** {len(df)}\n")
        f.write(f"- **Scenarios:** {', '.join(sorted(df['scenario'].unique()))}\n")
        f.write(f"- **Configurations:** {df['config'].nunique()}\n")
        f.write(f"- **Backends:** {', '.join(sorted(df['backend'].unique()))}\n\n")
        
        # Parameter space
        f.write("## Parameter Space\n\n")
        f.write("| Parameter | Values |\n")
        f.write("|-----------|--------|\n")
        f.write("| speedup | 60, 120, 240 |\n")
        f.write("| corrections_every_k | 10, 50, 100 |\n")
        f.write("| correction_delay_s | 0.5, 2.0, 5.0 |\n\n")
        
        # Configurations
        f.write("## Configurations\n\n")
        f.write("| Config | Speedup | Corrections Every K | Delay (s) |\n")
        f.write("|--------|---------|---------------------|----------|\n")
        configs = df[['config', 'speedup', 'corrections_every_k', 'correction_delay_s']].drop_duplicates()
        for _, row in configs.iterrows():
            f.write(f"| {row['config']} | {int(row['speedup'])} | {int(row['corrections_every_k'])} | {row['correction_delay_s']:.1f} |\n")
        f.write("\n")
        
        # Key Findings
        f.write("## Key Findings\n\n")
        
        # Backend comparison
        kafka_df = df[df['backend'] == 'kafka']
        redis_df = df[df['backend'] == 'redis']
        kafka_p50 = kafka_df['tti_p50'].mean()
        redis_p50 = redis_df['tti_p50'].mean()
        speedup_ratio = kafka_p50 / redis_p50
        
        f.write(f"### Backend Performance\n\n")
        f.write(f"- **Kafka Median TTI:** {kafka_p50:.2f} ms\n")
        f.write(f"- **Redis Median TTI:** {redis_p50:.2f} ms\n")
        f.write(f"- **Redis is {speedup_ratio:.1f}x faster** for median TTI\n\n")
        
        # Best configurations
        f.write("### Best Configurations\n\n")
        for backend in sorted(df['backend'].unique()):
            backend_df = df[df['backend'] == backend]
            if len(backend_df) > 0 and 'tti_p50' in backend_df.columns:
                best_idx = backend_df['tti_p50'].idxmin()
                best_config = backend_df.loc[best_idx, 'config']
                best_tti = backend_df.loc[best_idx, 'tti_p50']
                f.write(f"- **{backend.capitalize()}:** {best_config} (Median TTI = {best_tti:.2f} ms)\n")
        f.write("\n")
        
        # Parameter effects
        f.write("### Parameter Sensitivity\n\n")
        for param, param_name in [('speedup', 'Speedup'), 
                                   ('corrections_every_k', 'Correction Frequency'),
                                   ('correction_delay_s', 'Correction Delay')]:
            if param in df.columns:
                f.write(f"- **{param_name}:** ")
                values = sorted(df[param].unique())
                effects = []
                for v in values:
                    redis_df_param = df[(df['backend'] == 'redis') & (df[param] == v)]
                    redis_tti = redis_df_param['tti_p50'].mean() if len(redis_df_param) > 0 else 0
                    effects.append(f"{v}={redis_tti:.1f}ms")
                f.write(f"Redis: {', '.join(effects)}\n")
        f.write("\n")
        
        # Tables
        f.write("## Tables\n\n")
        f.write("See `tables/` directory for CSV files:\n")
        f.write("- `s4_backend_comparison.csv` - Overall Kafka vs Redis\n")
        f.write("- `s4_config_comparison.csv` - By configuration\n")
        f.write("- `s4_by_speedup.csv` - Speedup effect\n")
        f.write("- `s4_by_corrections_every_k.csv` - Correction frequency effect\n")
        f.write("- `s4_by_correction_delay_s.csv` - Correction delay effect\n")
        f.write("- `s4_all_data.csv` - Complete dataset\n\n")
        
        # Figures
        f.write("## Figures\n\n")
        f.write("See `figures/` directory for PNG files:\n")
        f.write("- `s4_tti_backend_boxplot.png` - TTI distribution by backend\n")
        f.write("- `s4_tti_by_config.png` - TTI by configuration\n")
        f.write("- `s4_speedup_impact.png` - Speedup effect\n")
        f.write("- `s4_correction_freq_impact.png` - Correction frequency effect\n")
        f.write("- `s4_correction_delay_impact.png` - Correction delay effect\n")
        if 'missed_window_100ms_rate' in df.columns:
            f.write("- `s4_missed_window_rates.png` - Missed window rates\n")
    
    print(f"Saved: s4_analysis_report.md")


def main():
    parser = argparse.ArgumentParser(description="Analyze S4 results")
    parser.add_argument("--csv", default="data/processed/results/paper_s4_parameter_sweep.csv",
                        help="Input S4 metrics CSV")
    parser.add_argument("--output", default="analysis_s4",
                        help="Output directory")
    args = parser.parse_args()
    
    print("Loading S4 data...")
    df = load_s4_data(args.csv)
    print(f"Loaded {len(df)} runs")
    
    output_dir = create_output_dir(args.output)
    
    print("\nGenerating tables...")
    generate_tables(df, output_dir)
    
    print("\nGenerating figures...")
    generate_figures(df, output_dir)
    
    print("\nGenerating report...")
    generate_report(df, output_dir)
    
    print(f"\n{'ANALYSIS COMPLETE':-^80}")
    print(f"Output directory: {output_dir.absolute()}")


if __name__ == "__main__":
    main()
