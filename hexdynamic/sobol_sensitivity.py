"""
Sobol Sensitivity Analysis Script

Performs global sensitivity analysis using Sobol indices to identify the most
influential parameters in the protection pipeline optimization.

Usage:
    python sobol_sensitivity.py <base_config.json> [options]

The script uses SALib for Saltelli sampling and Sobol index computation.
Each model evaluation calls run_pipeline from hexdynamic/protection_pipeline.py.
"""

import argparse
import json
import os
import sys
import copy
import time
import math
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, List, Tuple, Any, Optional

import numpy as np

# Add hexdynamic to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'hexdynamic'))

# SALib imports (will be added as dependency)
from SALib.sample import sobol as sobol_sample
from SALib.analyze import sobol

# Import the protection pipeline
from protection_pipeline import run_pipeline


# Default parameter definitions for sensitivity analysis
DEFAULT_PARAM_DEFS = [
    {"name": "total_patrol", "min": 10, "max": 30},
    {"name": "total_drones", "min": 1, "max": 8},
    {"name": "total_cameras", "min": 5, "max": 20},
    {"name": "total_camps", "min": 2, "max": 10}
]


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Sobol sensitivity analysis for protection pipeline optimization"
    )
    parser.add_argument(
        "base_config",
        help="Path to base input JSON configuration file"
    )
    parser.add_argument(
        "--params",
        type=str,
        default=None,
        help="Parameter definitions: file path or JSON string (default: built-in params)"
    )
    parser.add_argument(
        "--num-samples",
        type=int,
        default=512,
        help="Base number of Saltelli samples (default: 512)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./sobol_results",
        help="Directory for outputs (default: ./sobol_results)"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of parallel workers (default: CPU count)"
    )
    parser.add_argument(
        "--no-visualize",
        action="store_true",
        help="Skip chart generation (JSON outputs only)"
    )
    parser.add_argument(
        "--vectorized",
        action="store_true",
        help="Use vectorized coverage model for faster evaluation"
    )
    return parser.parse_args()


def load_base_config(path: str) -> dict:
    """Load and validate base configuration JSON."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Base config file not found: {path}")
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def parse_param_defs(params_input: Optional[str]) -> List[Dict[str, Any]]:
    """
    Parse parameter definitions from file path or JSON string.
    
    Args:
        params_input: File path, JSON string, or None for defaults
        
    Returns:
        List of parameter definition dicts with 'name', 'min', 'max' keys
        
    Raises:
        ValueError: If parameter bounds are invalid (min >= max)
    """
    if params_input is None:
        return copy.deepcopy(DEFAULT_PARAM_DEFS)
    
    # Check if it's a file path
    if os.path.exists(params_input):
        with open(params_input, 'r', encoding='utf-8') as f:
            param_defs = json.load(f)
    else:
        # Try to parse as JSON string
        param_defs = json.loads(params_input)
    
    # Validate parameter bounds
    for p in param_defs:
        if p["min"] >= p["max"]:
            raise ValueError(
                f"Invalid parameter bounds for '{p['name']}': min ({p['min']}) must be < max ({p['max']})"
            )
    
    return param_defs


def generate_samples(param_defs: List[Dict], num_samples: int, seed: Optional[int] = None) -> Tuple[Dict, np.ndarray]:
    """
    Generate Saltelli samples for Sobol analysis.
    
    Args:
        param_defs: List of parameter definitions
        num_samples: Base number of samples
        seed: Random seed for reproducibility
        
    Returns:
        Tuple of (problem dict, sample array)
    """
    problem = {
        "num_vars": len(param_defs),
        "names": [p["name"] for p in param_defs],
        "bounds": [[p["min"], p["max"]] for p in param_defs]
    }
    
    # Set random seed via numpy before sampling if provided
    if seed is not None:
        np.random.seed(seed)
    
    param_values = sobol_sample.sample(problem, num_samples)
    
    # Convert to integers for resource counts
    param_values = np.floor(param_values).astype(int)
    
    return problem, param_values


def evaluate_model(base_config: dict, params_dict: Dict[str, int], eval_idx: int, output_dir: str, vectorized: bool = False) -> Dict[str, Any]:
    """
    Run a single model evaluation with modified parameters.
    
    Args:
        base_config: Base configuration dict (will be deep-copied)
        params_dict: Parameter values to apply
        eval_idx: Evaluation index for tracking
        output_dir: Directory for intermediate files
        vectorized: Use vectorized coverage model
        
    Returns:
        Evaluation record dict with success status and results
    """
    # Deep copy to avoid modifying original
    config = copy.deepcopy(base_config)
    
    # Update constraints with sampled values
    if "constraints" not in config:
        config["constraints"] = {}
    for name, value in params_dict.items():
        config["constraints"][name] = value
    
    # Create evaluation-specific file paths
    input_path = os.path.join(output_dir, f"eval_{eval_idx:05d}_input.json")
    output_path = os.path.join(output_dir, f"eval_{eval_idx:05d}_output.json")
    
    # Write input file
    with open(input_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    
    try:
        # Run the pipeline (it writes output to file, doesn't return the result)
        run_pipeline(input_path, output_path, vectorized=vectorized)
        
        # Read the output file to extract metrics
        with open(output_path, 'r', encoding='utf-8') as f:
            result = json.load(f)
        
        # Extract metrics
        best_fitness = result.get("summary", {}).get("best_fitness", float('nan'))
        total_protection_benefit = result.get("summary", {}).get("total_protection_benefit", float('nan'))
        
        return {
            "eval_idx": eval_idx,
            "success": True,
            "params": params_dict,
            "best_fitness": float(best_fitness),
            "total_protection_benefit": float(total_protection_benefit),
            "error": None
        }
    except Exception as e:
        return {
            "eval_idx": eval_idx,
            "success": False,
            "params": params_dict,
            "best_fitness": float('nan'),
            "total_protection_benefit": float('nan'),
            "error": str(e)
        }


def _parallel_worker(args_tuple):
    """Top-level picklable worker function for parallel execution."""
    base_config, params_dict, eval_idx, output_dir, vectorized = args_tuple
    return evaluate_model(base_config, params_dict, eval_idx, output_dir, vectorized)


def run_analysis(base_config: dict, param_defs: List[Dict], num_samples: int, 
                 output_dir: str, seed: Optional[int], workers: int, vectorized: bool = False) -> Tuple[Dict, np.ndarray, np.ndarray, List[Dict]]:
    """
    Orchestrate all model evaluations.
    
    Args:
        base_config: Base configuration dict
        param_defs: Parameter definitions
        num_samples: Base number of samples
        output_dir: Output directory
        seed: Random seed
        workers: Number of parallel workers
        vectorized: Use vectorized coverage model
        
    Returns:
        Tuple of (problem, param_values, output_array, eval_records)
    """
    # Generate samples
    problem, param_values = generate_samples(param_defs, num_samples, seed)
    total_evals = len(param_values)
    
    print(f"Generated {total_evals} parameter combinations (N={num_samples}, k={len(param_defs)})")
    print(f"Total evaluations: {total_evals} (Saltelli sampling: N × (2k+2) = {num_samples} × {2*len(param_defs)+2})")
    print(f"Estimated time: {total_evals * 0.1:.0f}s sequential (with ~0.1s per eval)")
    print(f"Running {'sequential' if workers == 1 else f'parallel with {workers} workers'}...")
    print("-" * 60)
    if vectorized:
        print("Using vectorized coverage model")
    
    # Pre-generate all params_dict objects
    param_names = problem["names"]
    all_params = [
        {param_names[i]: int(param_values[j, i]) for i in range(len(param_names))}
        for j in range(total_evals)
    ]
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Run evaluations
    eval_records = []
    start_time = time.time()
    
    if workers == 1:
        # Sequential execution
        for j, params_dict in enumerate(all_params):
            print(f"[Eval {j+1}/{total_evals}]", end="\r")
            record = evaluate_model(base_config, params_dict, j, output_dir, vectorized)
            eval_records.append(record)
    else:
        # Parallel execution
        worker_args = [
            (base_config, all_params[j], j, output_dir, vectorized)
            for j in range(total_evals)
        ]
        
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_parallel_worker, args): args[2] for args in worker_args}
            completed = 0
            for future in as_completed(futures):
                completed += 1
                print(f"[Eval {completed}/{total_evals} done]", end="\r")
                record = future.result()
                eval_records.append(record)
    
    elapsed = time.time() - start_time
    
    # Sort by eval_idx
    eval_records.sort(key=lambda r: r["eval_idx"])
    
    # Extract output arrays for SALib
    output_array = np.array([r["best_fitness"] for r in eval_records])
    
    # Print summary
    successful = sum(1 for r in eval_records if r["success"])
    failed = total_evals - successful
    print(f"\nCompleted {total_evals} evaluations in {elapsed:.1f}s ({total_evals/elapsed:.2f} eval/s)")
    print(f"Successful: {successful}, Failed: {failed}")
    
    return problem, param_values, output_array, eval_records


def compute_sobol_indices(problem: Dict, output_array: np.ndarray, num_bootstrap: int = 1000) -> Dict:
    """
    Compute Sobol indices with bootstrap confidence intervals.
    
    Args:
        problem: SALib problem dict
        output_array: Array of output values
        num_bootstrap: Number of bootstrap resamples
        
    Returns:
        Dict with first_order, total_order, and convergence_summary
    """
    # Handle NaN values
    valid_mask = ~np.isnan(output_array)
    if not np.all(valid_mask):
        print(f"Warning: {np.sum(~valid_mask)} NaN values excluded from analysis")
    
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


def save_results(problem: Dict, param_values: np.ndarray, output_array: np.ndarray,
                 eval_records: List[Dict], sobol_indices: Dict, output_dir: str, meta: Dict):
    """
    Save all results to JSON files.
    
    Args:
        problem: SALib problem dict
        param_values: Sample array
        output_array: Output values
        eval_records: List of evaluation records
        sobol_indices: Computed Sobol indices
        output_dir: Output directory
        meta: Metadata dict
    """
    os.makedirs(output_dir, exist_ok=True)
    
    # Save evaluations
    evaluations = {
        "meta": meta,
        "evaluations": eval_records
    }
    with open(os.path.join(output_dir, "evaluations.json"), 'w', encoding='utf-8') as f:
        json.dump(evaluations, f, indent=2, ensure_ascii=False)
    
    # Save Sobol indices
    with open(os.path.join(output_dir, "sobol_indices.json"), 'w', encoding='utf-8') as f:
        json.dump({
            "meta": meta,
            "problem": {
                "num_vars": problem["num_vars"],
                "names": problem["names"],
                "bounds": problem["bounds"]
            },
            **sobol_indices
        }, f, indent=2, ensure_ascii=False)
    
    # Save analysis config
    analysis_config = {
        "meta": meta,
        "problem": {
            "num_vars": problem["num_vars"],
            "names": problem["names"],
            "bounds": problem["bounds"]
        },
        "param_defs": [
            {"name": problem["names"][i], "min": problem["bounds"][i][0], "max": problem["bounds"][i][1]}
            for i in range(problem["num_vars"])
        ]
    }
    with open(os.path.join(output_dir, "analysis_config.json"), 'w', encoding='utf-8') as f:
        json.dump(analysis_config, f, indent=2, ensure_ascii=False)
    
    print(f"Results saved to {output_dir}")


def plot_sensitivity(sobol_indices: Dict, param_names: List[str], output_dir: str):
    """
    Generate visualization plots.
    
    Args:
        sobol_indices: Computed Sobol indices
        param_names: Parameter names
        output_dir: Output directory
    """
    import matplotlib.pyplot as plt
    
    first_order = sobol_indices["first_order"]
    total_order = sobol_indices["total_order"]
    
    # Bar chart with S1 and ST
    fig, ax = plt.subplots(figsize=(10, 6))
    x = np.arange(len(param_names))
    width = 0.35
    
    s1_vals = [fo["value"] for fo in first_order]
    st_vals = [to["value"] for to in total_order]
    s1_err = [[fo["value"] - fo["conf_low"] for fo in first_order],
              [fo["conf_high"] - fo["value"] for fo in first_order]]
    st_err = [[to["value"] - to["conf_low"] for to in total_order],
              [to["conf_high"] - to["value"] for to in total_order]]
    
    ax.bar(x - width/2, s1_vals, width, label='First-order (S1)', yerr=s1_err, capsize=3)
    ax.bar(x + width/2, st_vals, width, label='Total-order (ST)', yerr=st_err, capsize=3)
    
    ax.set_xlabel('Parameter')
    ax.set_ylabel('Sobol Index')
    ax.set_title('Sobol Sensitivity Indices')
    ax.set_xticks(x)
    ax.set_xticklabels(param_names, rotation=45, ha='right')
    ax.legend()
    ax.set_ylim(0, 1)
    
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "sobol_indices.png"), dpi=150)
    plt.close()
    
    # Parameter ranking plot
    fig, ax = plt.subplots(figsize=(8, 6))
    sorted_idx = np.argsort(st_vals)[::-1]
    sorted_names = [param_names[i] for i in sorted_idx]
    sorted_st = [st_vals[i] for i in sorted_idx]
    
    ax.barh(sorted_names, sorted_st)
    ax.set_xlabel('Total-order Sobol Index')
    ax.set_title('Parameter Ranking by Total-order Index')
    ax.set_xlim(0, 1)
    
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "parameter_ranking.png"), dpi=150)
    plt.close()
    
    print(f"Visualizations saved to {output_dir}")


def main():
    """Main entry point."""
    args = parse_args()
    
    # Determine number of workers
    workers = args.workers if args.workers else os.cpu_count()
    
    print("=" * 60)
    print("Sobol Sensitivity Analysis")
    print("=" * 60)
    print(f"Base config: {args.base_config}")
    print(f"Num samples: {args.num_samples}")
    print(f"Output dir: {args.output_dir}")
    print(f"Seed: {args.seed}")
    print(f"Workers: {workers}")
    print(f"Vectorized: {args.vectorized}")
    print("=" * 60)
    
    # Load base config
    base_config = load_base_config(args.base_config)
    
    # Parse parameter definitions
    param_defs = parse_param_defs(args.params)
    print(f"Parameters: {[p['name'] for p in param_defs]}")
    
    # Run analysis
    problem, param_values, output_array, eval_records = run_analysis(
        base_config, param_defs, args.num_samples, args.output_dir, args.seed, workers, args.vectorized
    )
    
    # Compute Sobol indices
    print("\nComputing Sobol indices...")
    sobol_indices = compute_sobol_indices(problem, output_array)
    
    # Print convergence summary
    conv = sobol_indices["convergence_summary"]
    print(f"\nConvergence: {'All converged' if conv['all_converged'] else 'Some not converged'}")
    if conv["parameters_not_converged"]:
        print(f"  Not converged: {conv['parameters_not_converged']}")
    
    # Prepare metadata
    successful = sum(1 for r in eval_records if r["success"])
    failed = len(eval_records) - successful
    meta = {
        "base_config": os.path.abspath(args.base_config),
        "num_samples": args.num_samples,
        "total_evaluations": len(eval_records),
        "seed": args.seed,
        "workers": workers,
        "vectorized": args.vectorized,
        "successful_evaluations": successful,
        "failed_evaluations": failed
    }
    
    # Save results
    save_results(problem, param_values, output_array, eval_records, sobol_indices, args.output_dir, meta)
    
    # Generate visualizations
    if not args.no_visualize:
        if successful >= 10:
            plot_sensitivity(sobol_indices, problem["names"], args.output_dir)
        else:
            print("Warning: Fewer than 10 successful evaluations, skipping visualization")
    
    print("\nAnalysis complete!")


if __name__ == "__main__":
    main()
