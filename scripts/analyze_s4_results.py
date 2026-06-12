#!/usr/bin/env python3
"""
S4 Parameter Sensitivity Analysis
Analyzes how speedup, corrections_every_k, and correction_delay_s
affect S3 metrics (correction propagation latency, state staleness).

Outputs:
- docs/results/s4_analysis_summary.md
- docs/results/s4_parameter_effects.csv
- docs/results/s4_figures/
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
Path("docs/results/s4_figures").mkdir(parents=True, exist_ok=True)

# Set plotting style
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (12, 7)
plt.rcParams['font.size'] = 12
plt.rcParams['savefig.dpi'] = 300
plt.rcParams['savefig.bbox'] = 'tight'


def load_s4_metrics():
    """Load S4 metrics CSV."""
    s4_csv_path = Path("data/processed/results/paper_s4_parameter_sweep.csv")
    if not s4_csv_path.exists():
        print(f"S4 metrics CSV not found: {s4_csv_path}")
        return pd.DataFrame()
    
    df = pd.read_csv(s4_csv_path)
    
    # Extract run parameters from run_id
    # Format: s4_<scenario>_<config_name>_<backend>_rep<N>_<date>
    df['scenario'] = df['run'].apply(lambda x: x.split('_')[1])
    df['config_name'] = df['run'].apply(lambda x: x.split('_')[2])
    df['backend'] = df['run'].apply(lambda x: x.split('_')[3])
    df['rep'] = df['run'].apply(lambda x: int(x.split('_')[4].replace('rep', '')))
    
    # Parse percentile columns
    percentiles_cols = ['correction_propagation_latency_ms', 
                       'inconsistency_duration_ms',
                       'correction_planned_to_consume_latency_ms']
    
    for col in percentiles_cols:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: eval(x) if isinstance(x, str) and x.startswith('{') else x)
            for p in ['p50', 'p95', 'p99', 'mean', 'max', 'min']:
                new_col = f"{col}_{p}"
                df[new_col] = df[col].apply(lambda x: x.get(p, np.nan) if isinstance(x, dict) else np.nan)
    
    # Map config_name to parameters
    config_mapping = {
        'baseline': {'speedup': 120, 'corrections_every_k': 50, 'correction_delay_s': 2.0},
        'low_speedup': {'speedup': 60, 'corrections_every_k': 50, 'correction_delay_s': 2.0},
        'high_speedup': {'speedup': 240, 'corrections_every_k': 50, 'correction_delay_s': 2.0},
        'high_frequency': {'speedup': 120, 'corrections_every_k': 10, 'correction_delay_s': 2.0},
        'low_frequency': {'speedup': 120, 'corrections_every_k': 100, 'correction_delay_s': 2.0},
        'long_delay': {'speedup': 120, 'corrections_every_k': 50, 'correction_delay_s': 5.0},
        'short_delay': {'speedup': 120, 'corrections_every_k': 50, 'correction_delay_s': 0.5},
        'fast_corrections': {'speedup': 120, 'corrections_every_k': 10, 'correction_delay_s': 0.5}
    }
    
    for p in ['speedup', 'corrections_every_k', 'correction_delay_s']:
        df[p] = df['config_name'].apply(lambda x: config_mapping.get(x, {}).get(p, np.nan))
    
    return df


def analyze_parameter_effects(df: pd.DataFrame):
    """Analyze effect of each parameter on metrics."""
    print("Analyzing parameter effects...")
    
    # Focus on key metrics
    metrics = [
        'correction_propagation_latency_ms_p50',
        'correction_propagation_latency_ms_p95',
        'inconsistency_duration_ms_p50',
        'inconsistency_duration_ms_p95'
    ]
    
    results = []
    
    for parameter in ['speedup', 'corrections_every_k', 'correction_delay_s']:
        for metric in metrics:
            # Group by parameter value
            grouped = df.groupby(parameter)[metric].agg(['mean', 'std', 'min', 'max', 'count'])
            grouped = grouped.reset_index()
            grouped['parameter'] = parameter
            grouped['metric'] = metric
            results.append(grouped)
    
    if results:
        effects_df = pd.concat(results, ignore_index=True)
        effects_df.to_csv("docs/results/s4_parameter_effects.csv", index=False)
        print(f"  Saved: docs/results/s4_parameter_effects.csv")
        return effects_df
    return pd.DataFrame()


def generate_effect_plots(df: pd.DataFrame):
    """Generate plots showing parameter effects."""
    print("Generating effect plots...")
    
    metrics = [
        ('correction_propagation_latency_ms_p50', 'Correction Propagation Latency (p50)'),
        ('correction_propagation_latency_ms_p95', 'Correction Propagation Latency (p95)'),
        ('inconsistency_duration_ms_p50', 'Inconsistency Duration (p50)'),
        ('inconsistency_duration_ms_p95', 'Inconsistency Duration (p95)')
    ]
    
    parameters = ['speedup', 'corrections_every_k', 'correction_delay_s']
    
    for parameter, param_label in zip(parameters, ['Speedup Factor', 'Corrections Every K', 'Correction Delay (s)']):
        for metric, metric_label in metrics:
            plt.figure()
            
            # Filter to this parameter and metric
            plot_df = df[[parameter, metric, 'backend']].dropna()
            
            # Create boxplot
            sns.boxplot(data=plot_df, x=parameter, y=metric, hue='backend',
                        palette={'kafka': 'royalblue', 'redis': 'indianred'})
            
            plt.title(f'{metric_label} vs {param_label}')
            plt.xlabel(param_label)
            plt.ylabel('Latency (ms)')
            plt.legend(title='Backend')
            plt.tight_layout()
            
            filename = f"docs/results/s4_figures/{metric.split('_')[0]}_vs_{parameter}.png"
            plt.savefig(filename)
            plt.close()
            print(f"  Saved: {filename}")
    
    # Interaction plots
    for metric, metric_label in metrics:
        plt.figure(figsize=(14, 7))
        
        # Filter to this metric
        plot_df = df[[metric, 'speedup', 'corrections_every_k', 'correction_delay_s', 'backend']].dropna()
        
        # Create pairgrid or scatter plot matrix
        g = sns.pairplot(plot_df, 
                         vars=['speedup', 'corrections_every_k', 'correction_delay_s', metric],
                         hue='backend',
                         palette={'kafka': 'royalblue', 'redis': 'indianred'},
                         plot_kws={'alpha': 0.6, 's': 30})
        g.fig.suptitle(f'Parameter Interactions: {metric_label}', y=1.02)
        
        filename = f"docs/results/s4_figures/{metric.split('_')[0]}_interactions.png"
        g.savefig(filename)
        plt.close()
        print(f"  Saved: {filename}")


def generate_summary_markdown(df: pd.DataFrame, effects_df: pd.DataFrame):
    """Generate S4 analysis summary."""
    print("Generating summary markdown...")
    
    with open("docs/results/s4_analysis_summary.md", 'w') as f:
        f.write("# S4 Parameter Sensitivity Analysis\n\n")
        f.write("**Date:** 2026-06-12\n\n")
        f.write("**Objective:** Determine how speedup, corrections_every_k, and correction_delay_s affect S3 metrics\n\n")
        
        # Overview
        f.write("## Overview\n\n")
        f.write(f"- **Total Runs:** {len(df)}\n")
        f.write(f"- **Scenarios:** {df['scenario'].nunique()} ({', '.join(sorted(df['scenario'].unique()))})\n")
        f.write(f"- **Configurations:** {df['config_name'].nunique()}\n")
        f.write(f"- **Backends:** {df['backend'].nunique()}\n\n")
        
        # Parameter space
        f.write("## Parameter Space\n\n")
        f.write("| Parameter | Values Tested |\n")
        f.write("|-----------|----------------|\n")
        f.write("| speedup | 60, 120, 240 |\n")
        f.write("| corrections_every_k | 10, 50, 100 |\n")
        f.write("| correction_delay_s | 0.5, 2.0, 5.0 |\n\n")
        
        # Configurations
        f.write("## Configurations\n\n")
        f.write("| Config Name | Speedup | Corrections Every K | Delay (s) |\n")
        f.write("|-------------|---------|---------------------|----------|\n")
        
        configs = df[['config_name', 'speedup', 'corrections_every_k', 'correction_delay_s']].drop_duplicates()
        for _, row in configs.iterrows():
            f.write(f"| {row['config_name']} | {int(row['speedup'])} | {int(row['corrections_every_k'])} | {row['correction_delay_s']:.1f} |\n")
        
        f.write("\n")
        
        # Key Findings
        f.write("## Key Findings\n\n")
        
        # Analyze each parameter
        for parameter in ['speedup', 'corrections_every_k', 'correction_delay_s']:
            f.write(f"### Effect of {parameter}\n\n")
            
            param_df = effects_df[effects_df['parameter'] == parameter]
            if not param_df.empty:
                f.write(f"| Metric | Mean | Std | Min | Max | Count |\n")
                f.write(f"|--------|------|-----|-----|-----|-------|\n")
                
                for _, row in param_df.iterrows():
                    param_val = row[parameter]
                    if parameter == 'correction_delay_s':
                        param_val = f"{param_val:.1f}"
                    else:
                        param_val = int(param_val)
                    
                    f.write(f"| {row['metric']} | {row['mean']:.2f} | {row['std']:.2f} | {row['min']:.2f} | {row['max']:.2f} | {int(row['count'])} |\n")
            
            f.write("\n")
        
        # Figures
        f.write("## Figures\n\n")
        f.write("Generated figures in `docs/results/s4_figures/`:\n")
        f.write("- `*_vs_speedup.png` - Effect of speedup factor\n")
        f.write("- `*_vs_corrections_every_k.png` - Effect of correction frequency\n")
        f.write("- `*_vs_correction_delay_s.png` - Effect of correction delay\n")
        f.write("- `*_interactions.png` - Parameter interaction plots\n\n")
        
        # Recommendations
        f.write("## Recommendations\n\n")
        f.write("Based on S4 analysis, optimal parameter settings for:\n\n")
        f.write("- **Lowest correction propagation latency:** [TO BE FILLED AFTER RUN]\n")
        f.write("- **Lowest state staleness:** [TO BE FILLED AFTER RUN]\n")
        f.write("- **Best trade-off:** [TO BE FILLED AFTER RUN]\n\n")
    
    print("  Saved: docs/results/s4_analysis_summary.md")


def main():
    """Main analysis pipeline."""
    print("=" * 80)
    print("S4 PARAMETER SENSITIVITY ANALYSIS")
    print("=" * 80)
    
    # Load data
    print("\nLoading S4 metrics...")
    df = load_s4_metrics()
    
    if df.empty:
        print("ERROR: No S4 metrics data found. Run S4 trials first.")
        return 1
    
    print(f"Loaded {len(df)} runs")
    print(f"Scenarios: {sorted(df['scenario'].unique())}")
    print(f"Configurations: {sorted(df['config_name'].unique())}")
    print(f"Parameters: speedup={sorted(df['speedup'].unique())}, "
          f"corrections_every_k={sorted(df['corrections_every_k'].unique())}, "
          f"correction_delay_s={sorted(df['correction_delay_s'].unique())}")
    
    # Generate outputs
    effects_df = analyze_parameter_effects(df)
    generate_effect_plots(df)
    generate_summary_markdown(df, effects_df)
    
    print("\n" + "=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)
    print("Outputs generated:")
    print("  - docs/results/s4_analysis_summary.md")
    print("  - docs/results/s4_parameter_effects.csv")
    print("  - docs/results/s4_figures/*.png")
    print("=" * 80)
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
