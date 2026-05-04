"""
Analyze existing Sobol results from output JSON files.

Usage:
    python analyze_sobol_results.py <results_dir> [--output-dir OUTPUT_DIR]

This script reads the evaluation output files from a Sobol analysis and 
computes the Sobol indices, then generates visualization charts.
"""

import argparse
import json
import os
import glob
import numpy as np
import matplotlib.pyplot as plt
from SALib.analyze import sobol


def parse_args():
    parser = argparse.ArgumentParser(description="Analyze existing Sobol results")
    parser.add_argument("results_dir", help="Directory containing eval_*_output.json files")
    parser.add_argument("--output-dir", default=None, help="Output directory for results (default: same as results_dir)")
    parser.add_argument("--param-names", default=None, help="Comma-separated parameter names (default: auto-detect from config)")
    return parser.parse_args()


def load_evaluations(results_dir):
    """Load all evaluation output files from the results directory."""
    output_files = sorted(glob.glob(os.path.join(results_dir, "eval_*_output.json")))
    
    if not output_files:
        raise FileNotFoundError(f"No eval_*_output.json files found in {results_dir}")
    
    evaluations = []
    for f in output_files:
        try:
            with open(f, 'r', encoding='utf-8') as fp:
                data = json.load(fp)
            evaluations.append({
                "file": f,
                "summary": data.get("summary", {}),
                "success": True
            })
        except Exception as e:
            evaluations.append({
                "file": f,
                "summary": {},
                "success": False,
                "error": str(e)
            })
    
    return evaluations


def extract_outputs(evaluations):
    """Extract output metrics from evaluations."""
    best_fitness = []
    total_protection_benefit = []
    
    for ev in evaluations:
        if ev["success"]:
            summary = ev["summary"]
            bf = summary.get("best_fitness", float('nan'))
            tpb = summary.get("total_protection_benefit", float('nan'))
        else:
            bf = float('nan')
            tpb = float('nan')
        best_fitness.append(bf)
        total_protection_benefit.append(tpb)
    
    return np.array(best_fitness), np.array(total_protection_benefit)


def compute_sobol_indices(problem, output_array, num_bootstrap=1000):
    """Compute Sobol indices with bootstrap confidence intervals."""
    # Handle NaN values
    valid_mask = ~np.isnan(output_array)
    nan_count = np.sum(~valid_mask)
    if nan_count > 0:
        print(f"Warning: {nan_count} NaN values excluded from analysis")
    
    # Compute indices
    Si = sobol.analyze(problem, output_array, num_resamples=num_bootstrap)
    
    # Extract results
    first_order = []
    total_order = []
    
    for i, name in enumerate(problem["names"]):
        s1_val = float(Si["S1"][i])
        s1_conf = float(Si["S1_conf"][i])
        st_val = float(Si["ST"][i])
        st_conf = float(Si["ST_conf"][i])
        
        # Compute convergence
        s1_width = 2 * s1_conf
        st_width = 2 * st_conf
        
        first_order.append({
            "name": name,
            "value": s1_val,
            "conf_low": s1_val - s1_conf,
            "conf_high": s1_val + s1_conf,
            "converged": s1_width < 0.2
        })
        
        total_order.append({
            "name": name,
            "value": st_val,
            "conf_low": st_val - st_conf,
            "conf_high": st_val + st_conf,
            "converged": st_width < 0.2
        })
    
    # Convergence summary
    all_converged = all(fo["converged"] and to["converged"] for fo, to in zip(first_order, total_order))
    max_width = max(
        max(fo["conf_high"] - fo["conf_low"] for fo in first_order),
        max(to["conf_high"] - to["conf_low"] for to in total_order)
    )
    not_converged = [
        name for name, fo, to in zip(problem["names"], first_order, total_order)
        if not (fo["converged"] and to["converged"])
    ]
    
    return {
        "first_order": first_order,
        "total_order": total_order,
        "convergence_summary": {
            "all_converged": all_converged,
            "max_conf_width": round(max_width, 4),
            "parameters_not_converged": not_converged
        }
    }


def plot_sensitivity(sobol_indices, param_names, output_dir, metric_name="best_fitness"):
    """Generate visualization plots."""
    first_order = sobol_indices["first_order"]
    total_order = sobol_indices["total_order"]
    
    # Bar chart with S1 and ST
    fig, ax = plt.subplots(figsize=(10, 6))
    x = np.arange(len(param_names))
    width = 0.35
    
    s1_vals = [fo["value"] for fo in first_order]
    st_vals = [to["value"] for to in total_order]
    s1_err = [[max(0, fo["value"] - fo["conf_low"]) for fo in first_order],
              [max(0, fo["conf_high"] - fo["value"]) for fo in first_order]]
    st_err = [[max(0, to["value"] - to["conf_low"]) for to in total_order],
              [max(0, to["conf_high"] - to["value"]) for to in total_order]]
    
    ax.bar(x - width/2, s1_vals, width, label='First-order (S1)', yerr=s1_err, capsize=3)
    ax.bar(x + width/2, st_vals, width, label='Total-order (ST)', yerr=st_err, capsize=3)
    
    ax.set_xlabel('Parameter')
    ax.set_ylabel('Sobol Index')
    ax.set_title(f'Sobol Sensitivity Indices ({metric_name})')
    ax.set_xticks(x)
    ax.set_xticklabels(param_names, rotation=45, ha='right')
    ax.legend()
    ax.set_ylim(0, 1)
    ax.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
    
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, f"sobol_indices_{metric_name}.png"), dpi=150)
    plt.close()
    
    # Parameter ranking plot
    fig, ax = plt.subplots(figsize=(8, 6))
    sorted_idx = np.argsort(st_vals)[::-1]
    sorted_names = [param_names[i] for i in sorted_idx]
    sorted_st = [st_vals[i] for i in sorted_idx]
    
    ax.barh(sorted_names, sorted_st)
    ax.set_xlabel('Total-order Sobol Index')
    ax.set_title(f'Parameter Ranking by Total-order Index ({metric_name})')
    ax.set_xlim(0, max(1, max(sorted_st) * 1.1))
    
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, f"parameter_ranking_{metric_name}.png"), dpi=150)
    plt.close()
    
    print(f"Visualizations saved to {output_dir}")


def main():
    args = parse_args()
    
    results_dir = args.results_dir
    output_dir = args.output_dir if args.output_dir else results_dir
    os.makedirs(output_dir, exist_ok=True)
    
    print("=" * 60)
    print("Sobol Results Analysis")
    print("=" * 60)
    print(f"Results directory: {results_dir}")
    print(f"Output directory: {output_dir}")
    
    # Load analysis config if available
    config_path = os.path.join(results_dir, "analysis_config.json")
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        param_names = config.get("problem", {}).get("names", None)
        param_bounds = config.get("problem", {}).get("bounds", None)
        print(f"Loaded config: {param_names}")
    else:
        param_names = None
        param_bounds = None
    
    # Override with command line if provided
    if args.param_names:
        param_names = [n.strip() for n in args.param_names.split(",")]
    
    # Load evaluations
    print("\nLoading evaluation results...")
    evaluations = load_evaluations(results_dir)
    print(f"Found {len(evaluations)} evaluation files")
    
    successful = sum(1 for ev in evaluations if ev["success"])
    failed = len(evaluations) - successful
    print(f"Successful: {successful}, Failed: {failed}")
    
    if successful == 0:
        print("Error: No successful evaluations found")
        return
    
    # Extract outputs
    best_fitness, total_protection_benefit = extract_outputs(evaluations)
    
    # Auto-detect parameter names from first input file if not provided
    if param_names is None:
        input_files = sorted(glob.glob(os.path.join(results_dir, "eval_*_input.json")))
        if input_files:
            with open(input_files[0], 'r', encoding='utf-8') as f:
                first_input = json.load(f)
            constraints = first_input.get("constraints", {})
            param_names = list(constraints.keys())
            print(f"Auto-detected parameters: {param_names}")
    
    if param_names is None:
        # Default parameters
        param_names = ["total_patrol", "total_drones", "total_cameras", "total_camps"]
        print(f"Using default parameters: {param_names}")
    
    # Create problem definition
    num_vars = len(param_names)
    if param_bounds is None:
        # Use dummy bounds (not used for analysis, only for structure)
        param_bounds = [[0, 100] for _ in range(num_vars)]
    
    problem = {
        "num_vars": num_vars,
        "names": param_names,
        "bounds": param_bounds
    }
    
    # Compute Sobol indices for best_fitness
    print("\nComputing Sobol indices for best_fitness...")
    sobol_indices_fitness = compute_sobol_indices(problem, best_fitness)
    
    # Print results
    print("\nFirst-order indices (S1):")
    for fo in sobol_indices_fitness["first_order"]:
        print(f"  {fo['name']}: {fo['value']:.4f} [{fo['conf_low']:.4f}, {fo['conf_high']:.4f}]")
    
    print("\nTotal-order indices (ST):")
    for to in sobol_indices_fitness["total_order"]:
        print(f"  {to['name']}: {to['value']:.4f} [{to['conf_low']:.4f}, {to['conf_high']:.4f}]")
    
    # Convergence summary
    conv = sobol_indices_fitness["convergence_summary"]
    print(f"\nConvergence: {'All converged' if conv['all_converged'] else 'Some not converged'}")
    if conv["parameters_not_converged"]:
        print(f"  Not converged: {conv['parameters_not_converged']}")
    
    # Save results
    output_data = {
        "problem": problem,
        **sobol_indices_fitness
    }
    with open(os.path.join(output_dir, "sobol_indices_best_fitness.json"), 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    # Generate visualizations
    plot_sensitivity(sobol_indices_fitness, param_names, output_dir, "best_fitness")
    
    # Also analyze total_protection_benefit if available
    valid_benefit = ~np.isnan(total_protection_benefit)
    if np.sum(valid_benefit) > 10:
        print("\nComputing Sobol indices for total_protection_benefit...")
        sobol_indices_benefit = compute_sobol_indices(problem, total_protection_benefit)
        
        print("\nFirst-order indices (S1) for total_protection_benefit:")
        for fo in sobol_indices_benefit["first_order"]:
            print(f"  {fo['name']}: {fo['value']:.4f} [{fo['conf_low']:.4f}, {fo['conf_high']:.4f}]")
        
        print("\nTotal-order indices (ST) for total_protection_benefit:")
        for to in sobol_indices_benefit["total_order"]:
            print(f"  {to['name']}: {to['value']:.4f} [{to['conf_low']:.4f}, {to['conf_high']:.4f}]")
        
        # Save and plot
        output_data_benefit = {
            "problem": problem,
            **sobol_indices_benefit
        }
        with open(os.path.join(output_dir, "sobol_indices_total_benefit.json"), 'w', encoding='utf-8') as f:
            json.dump(output_data_benefit, f, indent=2, ensure_ascii=False)
        
        plot_sensitivity(sobol_indices_benefit, param_names, output_dir, "total_benefit")
    
    print("\nAnalysis complete!")


if __name__ == "__main__":
    main()
