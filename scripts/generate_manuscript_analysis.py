#!/usr/bin/env python3
"""
generate_manuscript_analysis.py
Generates complete analysis for the manuscript including:
- Summary tables comparing Kafka vs Redis
- Graphs (box plots, line charts, bar charts)
- Statistical comparisons
- Concurrency scaling analysis

Usage:
    python generate_manuscript_analysis.py --output-dir <dir>
    python generate_manuscript_analysis.py --run-list <file> --output-dir <dir>
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import seaborn as sns

# Set style for publication-quality plots
sns.set_style("whitegrid")
plt.rcParams['font.family'] = 'serif'
plt.rcParams['font.serif'] = ['Times New Roman'] + plt.rcParams['font.serif']
plt.rcParams['font.size'] = 12
plt.rcParams['axes.labelsize'] = 12
plt.rcParams['axes.titlesize'] = 14
plt.rcParams['xtick.labelsize'] = 10
plt.rcParams['ytick.labelsize'] = 10
plt.rcParams['legend.fontsize'] = 10
plt.rcParams['figure.figsize'] = (8, 6)
plt.rcParams['figure.dpi'] = 300


def load_run_data(runs: List[Path]) -> pd.DataFrame:
    """Load TTI data from multiple runs into a DataFrame."""
    all_data = []
    
    for run_dir in runs:
        tti_file = run_dir / "tti_summary.json"
        meta_file = run_dir / "meta.json"
        
        # Load TTI data
        if tti_file.exists():
            try:
                with open(tti_file, 'r', encoding='utf-8-sig') as f:
                    tti_data = json.load(f)
            except (json.JSONDecodeError, IOError):
                continue
        else:
            continue
        
        # Load metadata
        backend = "unknown"
        plan_csv = "unknown"
        if meta_file.exists():
            try:
                with open(meta_file, 'r', encoding='utf-8-sig') as f:
                    meta = json.load(f)
                    backend = meta.get("backend", "unknown")
                    plan_csv = meta.get("plan_csv", "unknown")
            except (json.JSONDecodeError, IOError):
                pass
        
        # Extract scenario from run_id or plan_csv
        run_id = run_dir.name
        scenario = "unknown"
        
        # Try to extract from run_id
        if "s2_" in run_id:
            scenario = "s2"
        elif "s2full_" in run_id:
            scenario = "s2full"
        elif "s2sf12_" in run_id:
            scenario = "s2sf12"
        elif "s2sf12j2_" in run_id:
            scenario = "s2sf12j2"
        elif "s3" in run_id:
            scenario = "s3"
        elif "concurrency_" in run_id:
            scenario = "concurrency"
        
        # Extract concurrency level if present
        concurrency = None
        if "concurrency_n" in run_id:
            parts = run_id.split("_")
            for part in parts:
                if part.startswith("n"):
                    try:
                        concurrency = int(part[1:])
                    except ValueError:
                        pass
        
        # Build row
        row = {
            "run_id": run_id,
            "backend": backend,
            "scenario": scenario,
            "concurrency": concurrency,
            "plan_csv": plan_csv,
        }
        
        # Add TTI metrics - handle both flat and nested structures
        if "tti_ms" in tti_data and isinstance(tti_data["tti_ms"], dict):
            # Nested structure (S2 format)
            tti_nested = tti_data["tti_ms"]
            row["tti_ms_p50"] = tti_nested.get("p50")
            row["tti_ms_p95"] = tti_nested.get("p95")
            row["tti_ms_p99"] = tti_nested.get("p99")
            row["tti_ms_max"] = tti_nested.get("max")
            row["tti_ms_mean"] = tti_nested.get("mean")
            row["tti_ms_std"] = tti_nested.get("std")
            row["tti_ms_min"] = tti_nested.get("min")
        else:
            # Flat structure (if exists)
            row["tti_ms_p50"] = tti_data.get("tti_ms_p50")
            row["tti_ms_p95"] = tti_data.get("tti_ms_p95")
            row["tti_ms_p99"] = tti_data.get("tti_ms_p99")
            row["tti_ms_max"] = tti_data.get("tti_ms_max")
            row["tti_ms_mean"] = tti_data.get("tti_ms_mean")
            row["tti_ms_std"] = tti_data.get("tti_ms_std")
            row["tti_ms_min"] = tti_data.get("tti_ms_min")
        
        # Add count metrics - handle both formats
        row["n_producer"] = tti_data.get("n_producer") or tti_data.get("n_produced")
        row["n_consumer"] = tti_data.get("n_consumer") or tti_data.get("n_consumed")
        row["n_matched"] = tti_data.get("n_matched")
        
        # Add transport latency if available
        if "transport_ms" in tti_data and isinstance(tti_data["transport_ms"], dict):
            row["transport_latency_ms_p50"] = tti_data["transport_ms"].get("p50")
        else:
            row["transport_latency_ms_p50"] = tti_data.get("transport_latency_ms_p50")
        
        all_data.append(row)
    
    return pd.DataFrame(all_data)


def create_comparison_table(df: pd.DataFrame, output_dir: Path) -> None:
    """Create a LaTeX/Markdown comparison table."""
    # Filter to main scenarios
    scenarios = ["s2", "s2full", "s2sf12", "s2sf12j2"]
    
    comparison_data = []
    for scenario in scenarios:
        scenario_df = df[df['scenario'] == scenario]
        if scenario_df.empty:
            continue
        
        for backend in ["kafka", "redis"]:
            backend_df = scenario_df[scenario_df['backend'] == backend]
            if backend_df.empty:
                continue
            
            row = {
                "Scenario": scenario,
                "Backend": backend.capitalize(),
                "Runs": len(backend_df),
                "TTI p50 (ms)": backend_df["tti_ms_p50"].mean(),
                "TTI p95 (ms)": backend_df["tti_ms_p95"].mean(),
                "TTI p99 (ms)": backend_df["tti_ms_p99"].mean(),
                "Events Matched": int(backend_df["n_matched"].mean()),
            }
            comparison_data.append(row)
    
    if not comparison_data:
        print("No data for comparison table")
        return
    
    comparison_df = pd.DataFrame(comparison_data)
    
    # Save as CSV
    comparison_df.to_csv(output_dir / "comparison_table.csv", index=False)
    
    # Save as Markdown
    with open(output_dir / "comparison_table.md", 'w', encoding='utf-8') as f:
        f.write("# Streaming Latency Comparison: Kafka vs Redis\n\n")
        f.write("## End-to-End Lag (Time-to-Insight) by Scenario\n\n")
        f.write(comparison_df.to_markdown(index=False, tablefmt="grid"))
        f.write("\n\n")
        f.write("*All values are averages across repetitions.\n")
    
    # Save as LaTeX
    with open(output_dir / "comparison_table.tex", 'w', encoding='utf-8') as f:
        f.write("\\begin{table*}[t]\n")
        f.write("\\centering\n")
        f.write("\\caption{End-to-End Latency Comparison: Kafka vs Redis Streams}\n")
        f.write("\\label{tab:latency_comparison}\n")
        f.write("\\begin{tabular}{l l c c c c c}\n")
        f.write("\\toprule\n")
        f.write("Scenario & Backend & Runs & TTI p50 (ms) & TTI p95 (ms) & TTI p99 (ms) & Events Matched \\\\\n")
        f.write("\\midrule\n")
        
        for _, row in comparison_df.iterrows():
            f.write(f"{row['Scenario']} & {row['Backend']} & {int(row['Runs'])} & "
                    f"{row['TTI p50 (ms)']:.2f} & {row['TTI p95 (ms)']:.2f} & "
                    f"{row['TTI p99 (ms)']:.2f} & {int(row['Events Matched'])} \\\\\n")
        
        f.write("\\bottomrule\n")
        f.write("\\end{tabular}\n")
        f.write("\\end{table*}\n")
    
    print(f"Comparison table saved to {output_dir}")


def create_boxplot(df: pd.DataFrame, output_dir: Path) -> None:
    """Create box plots comparing Kafka vs Redis TTI distributions."""
    # Filter to valid data
    df = df.dropna(subset=["tti_ms_p50", "backend"])
    
    if df.empty:
        print("No data for box plots")
        return
    
    # Define color palette
    palette = {"kafka": "#1f77b4", "redis": "#ff7f0e"}
    
    plt.figure(figsize=(10, 6))
    
    # Create box plot for each scenario
    scenarios = df['scenario'].unique()
    
    for i, scenario in enumerate(scenarios):
        scenario_df = df[df['scenario'] == scenario]
        
        # Position for this scenario
        positions = [i * 3 + 1, i * 3 + 2]
        
        # Get data for each backend
        kafka_data = scenario_df[scenario_df['backend'] == 'kafka']['tti_ms_p50']
        redis_data = scenario_df[scenario_df['backend'] == 'redis']['tti_ms_p50']
        
        if not kafka_data.empty:
            plt.boxplot(kafka_data, positions=[positions[0]], widths=0.6, patch_artist=True)
        if not redis_data.empty:
            plt.boxplot(redis_data, positions=[positions[1]], widths=0.6, patch_artist=True)
    
    # Customize plot
    plt.title("Time-to-Insight (TTI) Distribution by Backend and Scenario")
    plt.ylabel("TTI (ms)")
    plt.xticks(
        [i * 3 + 1.5 for i in range(len(scenarios))],
        scenarios,
        rotation=45
    )
    # Create custom legend handles
    legend_elements = [
        plt.Rectangle((0,0), 1, 1, fc=palette['kafka'], label='Kafka'),
        plt.Rectangle((0,0), 1, 1, fc=palette['redis'], label='Redis')
    ]
    plt.legend(handles=legend_elements, loc='upper right')
    plt.tight_layout()
    
    # Save
    plt.savefig(output_dir / "tti_boxplot_by_scenario.png")
    plt.savefig(output_dir / "tti_boxplot_by_scenario.pdf")
    plt.close()
    
    print(f"Box plot saved to {output_dir}")


def create_concurrency_scaling_plot(df: pd.DataFrame, output_dir: Path) -> None:
    """Create concurrency scaling plots."""
    # Filter to concurrency data
    concurrency_df = df[df['concurrency'].notna()].copy()
    
    if concurrency_df.empty:
        print("No concurrency data for scaling plots")
        return
    
    # Group by backend and concurrency
    grouped = concurrency_df.groupby(['backend', 'concurrency', 'run_id']).agg({
        'tti_ms_p50': 'mean',
        'tti_ms_p95': 'mean',
        'tti_ms_p99': 'mean',
    }).reset_index()
    
    # Create line plot for p50
    plt.figure(figsize=(10, 6))
    
    for backend in ['kafka', 'redis']:
        backend_data = grouped[grouped['backend'] == backend]
        if backend_data.empty:
            continue
        
        # Sort by concurrency
        backend_data = backend_data.sort_values('concurrency')
        
        plt.plot(
            backend_data['concurrency'],
            backend_data['tti_ms_p50'],
            marker='o',
            label=backend.capitalize(),
            linewidth=2,
            markersize=8
        )
    
    plt.title("TTI p50 vs Concurrency Level")
    plt.xlabel("Number of Concurrent Feeds (N)")
    plt.ylabel("TTI p50 (ms)")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    
    plt.savefig(output_dir / "concurrency_scaling_p50.png")
    plt.savefig(output_dir / "concurrency_scaling_p50.pdf")
    plt.close()
    
    # Create p95 plot
    plt.figure(figsize=(10, 6))
    
    for backend in ['kafka', 'redis']:
        backend_data = grouped[grouped['backend'] == backend]
        if backend_data.empty:
            continue
        
        backend_data = backend_data.sort_values('concurrency')
        
        plt.plot(
            backend_data['concurrency'],
            backend_data['tti_ms_p95'],
            marker='s',
            label=backend.capitalize(),
            linewidth=2,
            markersize=8
        )
    
    plt.title("TTI p95 vs Concurrency Level")
    plt.xlabel("Number of Concurrent Feeds (N)")
    plt.ylabel("TTI p95 (ms)")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    
    plt.savefig(output_dir / "concurrency_scaling_p95.png")
    plt.savefig(output_dir / "concurrency_scaling_p95.pdf")
    plt.close()
    
    print(f"Concurrency scaling plots saved to {output_dir}")


def create_violin_plot(df: pd.DataFrame, output_dir: Path) -> None:
    """Create violin plots showing full distribution."""
    df = df.dropna(subset=["tti_ms_p50", "backend", "scenario"])
    
    if df.empty:
        print("No data for violin plots")
        return
    
    plt.figure(figsize=(12, 8))
    
    # Get all scenarios
    scenarios = sorted(df['scenario'].unique())
    
    # Create a color palette
    palette = {"kafka": "#1f77b4", "redis": "#ff7f0e"}
    
    positions = []
    backend_labels = []
    tti_values = []
    colors = []
    
    for scenario in scenarios:
        scenario_df = df[df['scenario'] == scenario]
        
        for backend in ['kafka', 'redis']:
            backend_df = scenario_df[scenario_df['backend'] == backend]
            if not backend_df.empty:
                positions.extend([scenario] * len(backend_df))
                backend_labels.extend([backend.capitalize()] * len(backend_df))
                tti_values.extend(backend_df['tti_ms_p50'].tolist())
                colors.extend([palette[backend]] * len(backend_df))
    
    if not positions:
        print("No data for violin plot")
        return
    
    # Create split violin plot
    # Map backend labels to palette keys
    palette_mapping = {label: palette[label.lower()] for label in set(backend_labels)}
    
    ax = sns.violinplot(
        x=positions,
        y=tti_values,
        hue=backend_labels,
        palette=palette_mapping,
        split=True,
        inner='quartile',
        cut=0
    )
    
    plt.title("TTI p50 Distribution by Scenario and Backend")
    plt.xlabel("Scenario")
    plt.ylabel("TTI p50 (ms)")
    plt.xticks(rotation=45)
    plt.legend(title="Backend")
    plt.tight_layout()
    
    plt.savefig(output_dir / "tti_violin_plot.png")
    plt.savefig(output_dir / "tti_violin_plot.pdf")
    plt.close()
    
    print(f"Violin plot saved to {output_dir}")


def create_statistical_summary(df: pd.DataFrame, output_dir: Path) -> None:
    """Create a statistical summary table."""
    # Group by backend and scenario
    grouped = df.groupby(['backend', 'scenario']).agg({
        'tti_ms_p50': ['mean', 'std', 'min', 'max'],
        'tti_ms_p95': ['mean', 'std'],
        'tti_ms_p99': ['mean', 'std'],
        'n_matched': 'mean',
    }).round(2)
    
    # Flatten multi-index columns
    grouped.columns = ['_'.join(col).strip() for col in grouped.columns.values]
    grouped = grouped.reset_index()
    
    # Save as CSV
    grouped.to_csv(output_dir / "statistical_summary.csv", index=False)
    
    # Save as Markdown
    with open(output_dir / "statistical_summary.md", 'w', encoding='utf-8') as f:
        f.write("# Statistical Summary\n\n")
        f.write("## TTI Statistics by Backend and Scenario\n\n")
        f.write(grouped.to_markdown(index=False, tablefmt="grid"))
    
    print(f"Statistical summary saved to {output_dir}")


def create_event_count_table(df: pd.DataFrame, output_dir: Path) -> None:
    """Create a table showing event counts and match rates."""
    # Group by backend and scenario
    grouped = df.groupby(['backend', 'scenario']).agg({
        'n_producer': 'mean',
        'n_consumer': 'mean',
        'n_matched': ['mean', 'sum'],
    }).round(0)
    
    # Calculate match rate manually
    rows = []
    for (backend, scenario), group_data in grouped.iterrows():
        n_producer = group_data['n_producer'].item() if hasattr(group_data['n_producer'], 'item') else group_data['n_producer']
        n_matched_mean = group_data[('n_matched', 'mean')].item() if hasattr(group_data[('n_matched', 'mean')], 'item') else group_data[('n_matched', 'mean')]
        n_matched_sum = group_data[('n_matched', 'sum')].item() if hasattr(group_data[('n_matched', 'sum')], 'item') else group_data[('n_matched', 'sum')]
        n_consumer = group_data['n_consumer'].item() if hasattr(group_data['n_consumer'], 'item') else group_data['n_consumer']
        
        match_rate = (n_matched_mean / n_producer * 100) if n_producer and n_producer > 0 else 0
        
        rows.append({
            'backend': backend,
            'scenario': scenario,
            'Avg Producer Events': n_producer,
            'Avg Consumer Events': n_consumer,
            'Avg Matched Events': n_matched_mean,
            'Total Matched Events': n_matched_sum,
            'Match Rate (%)': round(match_rate, 2)
        })
    
    result = pd.DataFrame(rows)
    
    # Save as CSV
    result.to_csv(output_dir / "event_counts.csv", index=False)
    
    # Save as Markdown
    with open(output_dir / "event_counts.md", 'w', encoding='utf-8') as f:
        f.write("# Event Count Summary\n\n")
        f.write("## Matching Statistics by Backend and Scenario\n\n")
        f.write(result.to_markdown(index=False, tablefmt="grid"))
    
    print(f"Event count table saved to {output_dir}")


def create_cdf_plot(df: pd.DataFrame, output_dir: Path) -> None:
    """Create CDF plots for TTI distributions."""
    df = df.dropna(subset=["tti_ms_p50", "backend"])
    
    if df.empty:
        print("No data for CDF plots")
        return
    
    plt.figure(figsize=(10, 6))
    
    for backend in ['kafka', 'redis']:
        backend_df = df[df['backend'] == backend]
        if backend_df.empty:
            continue
        
        # Sort TTI values
        tti_values = backend_df['tti_ms_p50'].sort_values().tolist()
        cdf = np.arange(1, len(tti_values) + 1) / len(tti_values) * 100
        
        plt.plot(tti_values, cdf, label=backend.capitalize(), linewidth=2)
    
    plt.title("CDF of Time-to-Insight (p50)")
    plt.xlabel("TTI (ms)")
    plt.ylabel("Cumulative Probability (%)")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    
    plt.savefig(output_dir / "tti_cdf.png")
    plt.savefig(output_dir / "tti_cdf.pdf")
    plt.close()
    
    print(f"CDF plot saved to {output_dir}")


def create_latency_decomposition(df: pd.DataFrame, output_dir: Path) -> None:
    """Create latency decomposition charts (if transport latency is available)."""
    if 'transport_latency_ms_p50' not in df.columns:
        print("Transport latency data not available for decomposition")
        return
    
    df = df.dropna(subset=["tti_ms_p50", "transport_latency_ms_p50", "backend"])
    
    if df.empty:
        print("No data for latency decomposition")
        return
    
    plt.figure(figsize=(10, 6))
    
    for backend in ['kafka', 'redis']:
        backend_df = df[df['backend'] == backend]
        if backend_df.empty:
            continue
        
        tti = backend_df['tti_ms_p50'].mean()
        transport = backend_df['transport_latency_ms_p50'].mean()
        scheduling = tti - transport
        
        plt.bar(
            [backend.capitalize()],
            [scheduling],
            label=f'{backend.capitalize()} - Scheduling',
            color='skyblue'
        )
        plt.bar(
            [backend.capitalize()],
            [transport],
            bottom=[scheduling],
            label=f'{backend.capitalize()} - Transport',
            color='salmon'
        )
    
    plt.title("Latency Decomposition: Scheduling vs Transport")
    plt.ylabel("Latency (ms)")
    plt.legend()
    plt.tight_layout()
    
    plt.savefig(output_dir / "latency_decomposition.png")
    plt.savefig(output_dir / "latency_decomposition.pdf")
    plt.close()
    
    print(f"Latency decomposition saved to {output_dir}")


def main():
    ap = argparse.ArgumentParser(
        description="Generate complete manuscript analysis with graphs and tables"
    )
    ap.add_argument(
        "--run-list",
        type=str,
        help="File containing list of run directories (one per line)"
    )
    ap.add_argument(
        "--runs-dir",
        type=str,
        default="runs",
        help="Directory containing run subdirectories (default: runs)"
    )
    ap.add_argument(
        "--output-dir",
        type=str,
        default="docs/results/analysis",
        help="Output directory for analysis files (default: docs/results/analysis)"
    )
    ap.add_argument(
        "--scenarios",
        nargs="+",
        default=None,
        help="Specific scenarios to include (default: all)"
    )
    
    args = ap.parse_args()
    
    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load run data
    runs_to_analyze = []
    
    if args.run_list:
        # Try different encodings for the run list file
        encodings = ['utf-8-sig', 'utf-16', 'utf-8']
        found_encoding = None
        for encoding in encodings:
            try:
                with open(args.run_list, 'r', encoding=encoding) as test_f:
                    test_f.read()
                found_encoding = encoding
                break
            except (UnicodeDecodeError, IOError):
                continue
        
        if found_encoding is None:
            print(f"Cannot read run list file with any encoding: {args.run_list}")
            sys.exit(1)
        
        with open(args.run_list, 'r', encoding=found_encoding) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    # Handle backslashes
                    line = line.replace('\\', '/')
                    run_path = Path(line)
                    if not run_path.is_absolute():
                        if 'runs' in str(run_path).lower():
                            run_path = run_path
                        else:
                            run_path = Path(args.runs_dir) / run_path
                    runs_to_analyze.append(run_path)
    else:
        # Analyze all runs in directory
        runs_dir = Path(args.runs_dir)
        if runs_dir.exists():
            for item in sorted(runs_dir.iterdir()):
                if item.is_dir() and not item.name.startswith('_'):
                    runs_to_analyze.append(item)
    
    if not runs_to_analyze:
        print("No runs found to analyze")
        sys.exit(1)
    
    print(f"Loading data from {len(runs_to_analyze)} runs...")
    df = load_run_data(runs_to_analyze)
    
    if df.empty:
        print("No data loaded. Check that runs have valid tti_summary.json files.")
        sys.exit(1)
    
    print(f"Loaded {len(df)} data points")
    
    # Filter by scenarios if specified
    if args.scenarios:
        df = df[df['scenario'].isin(args.scenarios)]
        print(f"Filtered to {len(df)} data points for scenarios: {args.scenarios}")
    
    # Generate all outputs
    print("\nGenerating analysis outputs...")
    
    create_comparison_table(df, output_dir)
    create_boxplot(df, output_dir)
    create_violin_plot(df, output_dir)
    create_cdf_plot(df, output_dir)
    create_statistical_summary(df, output_dir)
    create_event_count_table(df, output_dir)
    create_concurrency_scaling_plot(df, output_dir)
    create_latency_decomposition(df, output_dir)
    
    # Save raw data
    df.to_csv(output_dir / "raw_analysis_data.csv", index=False)
    
    print("\n" + "=" * 60)
    print("ANALYSIS COMPLETE")
    print("=" * 60)
    print(f"Output directory: {output_dir}")
    print(f"Total runs analyzed: {len(df)}")
    print(f"Scenarios: {df['scenario'].unique().tolist()}")
    print(f"Backends: {df['backend'].unique().tolist()}")
    
    if df['concurrency'].notna().any():
        print(f"Concurrency levels: {sorted(df['concurrency'].dropna().unique().tolist())}")


if __name__ == "__main__":
    main()
