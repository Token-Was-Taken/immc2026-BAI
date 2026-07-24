"""
Sobol Sensitivity Analysis for Synergy Coefficients (alpha_pd, alpha_pc)

Analyzes how the synergy coefficients alpha_pd (Patrol+Drone) and alpha_pc
(Patrol+Camera) affect the overall protection benefit, alongside resource
quantity variables.

This script extends the standard Sobol analysis by treating synergy coefficients
as input variables, allowing us to quantify:
  - First-order sensitivity of each synergy coefficient
  - Interaction effects between synergy coefficients and resource quantities

Usage:
    python sobol_synergy_analysis.py <base_config.json> [options]

Example:
    python sobol_synergy_analysis.py base.json --num-samples 256 --workers 8
"""

import argparse
import json
import os
import sys
import copy
import time
import numpy as np
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, List, Tuple, Any, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'hexdynamic'))

from protection_pipeline import run_pipeline


DEFAULT_SYNERGY_PARAM_DEFS = [
    {"name": "alpha_pd", "min": 0.0, "max": 1.0},
    {"name": "alpha_pc", "min": 0.0, "max": 0.5},
    {"name": "total_patrol", "min": 10, "max": 30},
    {"name": "total_drones", "min": 1, "max": 8},
    {"name": "total_cameras", "min": 5, "max": 20},
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Sobol sensitivity analysis for synergy coefficients"
    )
    parser.add_argument("base_config", help="Path to base input JSON configuration file")
    parser.add_argument("--params", type=str, default=None,
                        help="Parameter definitions: file path or JSON string")
    parser.add_argument("--num-samples", type=int, default=256,
                        help="Base number of Saltelli samples (default: 256)")
    parser.add_argument("--output-dir", type=str, default="./sobol_synergy_results",
                        help="Directory for outputs")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--workers", type=int, default=None, help="Parallel workers")
    parser.add_argument("--vectorized", action="store_true",
                        help="Use vectorized coverage model")
    parser.add_argument("--gpu", action="store_true",
                        help="Use GPU acceleration (OpenCL) with vectorized model")
    parser.add_argument("--resume", action="store_true",
                        help="Resume from checkpoint.json in output dir if it exists")
    return parser.parse_args()


def parse_param_defs(params_input: Optional[str]) -> List[Dict[str, Any]]:
    if params_input is None:
        return copy.deepcopy(DEFAULT_SYNERGY_PARAM_DEFS)
    if os.path.exists(params_input):
        with open(params_input, 'r', encoding='utf-8') as f:
            param_defs = json.load(f)
    else:
        param_defs = json.loads(params_input)
    for p in param_defs:
        if p["min"] >= p["max"]:
            raise ValueError(f"Invalid bounds for '{p['name']}': min >= max")
    return param_defs


def evaluate_model(base_config, params_dict: Dict[str, Any],
                   eval_idx: int, output_dir: str,
                   vectorized: bool = False, use_gpu: bool = False) -> Dict[str, Any]:
    # Load config from file if a path is given (saves memory in parallel mode)
    if isinstance(base_config, str):
        with open(base_config, 'r', encoding='utf-8') as f:
            base_config = json.load(f)
    config = copy.deepcopy(base_config)

    if "constraints" not in config:
        config["constraints"] = {}
    if "coverage_params" not in config:
        config["coverage_params"] = {}

    for name, value in params_dict.items():
        if name.startswith("alpha_"):
            config["coverage_params"][name] = value
        elif name in ("total_patrol", "total_drones", "total_cameras",
                      "total_camps", "total_fence_length"):
            config["constraints"][name] = int(value)
        elif name in ("wp", "wd", "wc", "wf",
                      "patrol_radius", "drone_radius", "camera_radius",
                      "fence_protection"):
            config["coverage_params"][name] = value

    input_path = os.path.join(output_dir, f"eval_{eval_idx:05d}_input.json")
    output_path = os.path.join(output_dir, f"eval_{eval_idx:05d}_output.json")

    os.makedirs(output_dir, exist_ok=True)
    with open(input_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    try:
        run_pipeline(input_path, output_path, vectorized=vectorized, use_gpu=use_gpu)
        with open(output_path, 'r', encoding='utf-8') as f:
            result = json.load(f)
        best_fitness = result.get("summary", {}).get("best_fitness", float('nan'))
        total_protection_benefit = result.get("summary", {}).get(
            "total_protection_benefit", float('nan'))
        return {
            "eval_idx": eval_idx, "success": True,
            "params": params_dict,
            "best_fitness": float(best_fitness),
            "total_protection_benefit": float(total_protection_benefit),
            "error": None
        }
    except Exception as e:
        return {
            "eval_idx": eval_idx, "success": False,
            "params": params_dict,
            "best_fitness": float('nan'),
            "total_protection_benefit": float('nan'),
            "error": str(e)
        }


def _parallel_worker(args_tuple):
    base_config, params_dict, eval_idx, output_dir, vectorized, use_gpu = args_tuple
    return evaluate_model(base_config, params_dict, eval_idx, output_dir, vectorized, use_gpu)


# ---------------------------------------------------------------------------
# Checkpoint for resume support
# ---------------------------------------------------------------------------

def load_checkpoint(output_dir: str) -> Tuple[Optional[Dict], Dict[int, Dict]]:
    """Load checkpoint.json if it exists.

    Returns:
        (meta, {eval_idx: record}) or (None, {}) if no valid checkpoint.
    """
    ckpt_path = os.path.join(output_dir, "checkpoint.json")
    if not os.path.exists(ckpt_path):
        return None, {}
    try:
        with open(ckpt_path, 'r', encoding='utf-8') as f:
            ckpt = json.load(f)
        meta = ckpt.get("meta")
        completed = {int(k): v for k, v in ckpt.get("completed", {}).items()}
        return meta, completed
    except (json.JSONDecodeError, KeyError, ValueError):
        return None, {}


def save_checkpoint(output_dir: str, meta: Dict, completed: Dict[int, Dict]) -> None:
    """Atomically save checkpoint.json (write to .tmp then rename)."""
    ckpt_path = os.path.join(output_dir, "checkpoint.json")
    tmp_path = ckpt_path + ".tmp"
    data = {
        "meta": meta,
        "completed": {str(k): v for k, v in completed.items()},
    }
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp_path, ckpt_path)


def compute_sobol_indices(problem: Dict, output_array: np.ndarray,
                          num_bootstrap: int = 1000) -> Dict:
    valid_mask = ~np.isnan(output_array)
    if not np.all(valid_mask):
        print(f"Warning: {np.sum(~valid_mask)} NaN values excluded")

    from SALib.analyze import sobol
    Si = sobol.analyze(problem, output_array, num_resamples=num_bootstrap)

    first_order = []
    total_order = []
    second_order = []

    for i, name in enumerate(problem["names"]):
        s1_val = float(Si["S1"][i])
        s1_conf = float(Si["S1_conf"][i])
        st_val = float(Si["ST"][i])
        st_conf = float(Si["ST_conf"][i])

        first_order.append({
            "name": name, "value": s1_val,
            "conf_low": s1_val - s1_conf, "conf_high": s1_val + s1_conf,
            "converged": 2 * s1_conf < 0.2
        })
        total_order.append({
            "name": name, "value": st_val,
            "conf_low": st_val - st_conf, "conf_high": st_val + st_conf,
            "converged": 2 * st_conf < 0.2
        })

    if "S2" in Si and Si["S2"] is not None:
        names = problem["names"]
        k = len(names)
        for i in range(k):
            for j in range(i + 1, k):
                s2_val = float(Si["S2"][i][j])
                s2_conf = float(Si["S2_conf"][i][j])
                if not np.isnan(s2_val):
                    second_order.append({
                        "pair": f"{names[i]} x {names[j]}",
                        "names": [names[i], names[j]],
                        "indices": [i, j],
                        "value": s2_val,
                        "conf_low": s2_val - s2_conf,
                        "conf_high": s2_val + s2_conf
                    })

    interaction_effects = []
    for fo, to in zip(first_order, total_order):
        interaction = to["value"] - fo["value"]
        interaction_effects.append({
            "name": fo["name"],
            "interaction_effect": max(0.0, interaction),
            "first_order": fo["value"],
            "total_order": to["value"]
        })

    all_converged = all(fo["converged"] and to["converged"]
                        for fo, to in zip(first_order, total_order))
    max_width = max(
        max(fo["conf_high"] - fo["conf_low"] for fo in first_order),
        max(to["conf_high"] - to["conf_low"] for to in total_order)
    )

    return {
        "first_order": first_order,
        "total_order": total_order,
        "second_order": second_order,
        "interaction_effects": interaction_effects,
        "convergence_summary": {
            "all_converged": all_converged,
            "max_conf_width": round(max_width, 4),
            "parameters_not_converged": [
                name for name, fo, to in zip(problem["names"], first_order, total_order)
                if not (fo["converged"] and to["converged"])
            ]
        }
    }


def plot_synergy_sensitivity(sobol_indices: Dict, param_names: List[str],
                             output_dir: str):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    first_order = sobol_indices["first_order"]
    total_order = sobol_indices["total_order"]
    second_order = sobol_indices.get("second_order", [])

    fig, axes = plt.subplots(1, 3, figsize=(18, 6))

    # Plot 1: S1 and ST bar chart
    ax = axes[0]
    x = np.arange(len(param_names))
    width = 0.35
    s1_vals = [fo["value"] for fo in first_order]
    st_vals = [to["value"] for to in total_order]
    s1_err = [[fo["value"] - fo["conf_low"] for fo in first_order],
              [fo["conf_high"] - fo["value"] for fo in first_order]]
    st_err = [[to["value"] - to["conf_low"] for to in total_order],
              [to["conf_high"] - to["value"] for to in total_order]]
    ax.bar(x - width / 2, s1_vals, width, label='First-order (S1)',
           yerr=s1_err, capsize=3, color='steelblue')
    ax.bar(x + width / 2, st_vals, width, label='Total-order (ST)',
           yerr=st_err, capsize=3, color='coral')
    ax.set_xlabel('Parameter')
    ax.set_ylabel('Sobol Index')
    ax.set_title('First-order & Total-order Indices')
    ax.set_xticks(x)
    ax.set_xticklabels(param_names, rotation=45, ha='right')
    ax.legend()
    ax.set_ylim(0, max(max(st_vals) * 1.3, 0.1))

    # Plot 2: Interaction effects (ST - S1)
    ax = axes[1]
    interactions = sobol_indices["interaction_effects"]
    names = [ie["name"] for ie in interactions]
    ie_vals = [ie["interaction_effect"] for ie in interactions]
    colors = ['#e74c3c' if n.startswith('alpha_') else '#3498db' for n in names]
    ax.barh(names, ie_vals, color=colors)
    ax.set_xlabel('Interaction Effect (ST - S1)')
    ax.set_title('Interaction Effects by Parameter')
    ax.axvline(x=0, color='gray', linestyle='--', linewidth=0.5)

    # Plot 3: Second-order indices (top pairs)
    ax = axes[2]
    if second_order:
        sorted_s2 = sorted(second_order, key=lambda x: abs(x["value"]), reverse=True)
        top_n = min(10, len(sorted_s2))
        top_s2 = sorted_s2[:top_n]
        pair_names = [s2["pair"] for s2 in top_s2]
        s2_vals = [s2["value"] for s2 in top_s2]
        s2_err_low = [max(0, s2["value"] - s2["conf_low"]) for s2 in top_s2]
        s2_err_high = [max(0, s2["conf_high"] - s2["value"]) for s2 in top_s2]
        colors_s2 = ['#e74c3c' if 'alpha_' in s2["pair"] else '#3498db'
                     for s2 in top_s2]
        ax.barh(pair_names, s2_vals,
                xerr=[s2_err_low, s2_err_high],
                capsize=3, color=colors_s2)
        ax.set_xlabel('Second-order Index (S2)')
        ax.set_title('Top Second-order Interactions')
        ax.axvline(x=0, color='gray', linestyle='--', linewidth=0.5)
    else:
        ax.text(0.5, 0.5, 'No S2 data', ha='center', va='center',
                transform=ax.transAxes)

    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "sobol_synergy_indices.png"), dpi=150)
    plt.close()

    # Separate plot: synergy-specific comparison
    fig, ax = plt.subplots(figsize=(10, 6))
    synergy_names = [fo["name"] for fo in first_order
                     if fo["name"].startswith("alpha_")]
    resource_names = [fo["name"] for fo in first_order
                      if not fo["name"].startswith("alpha_")]

    if synergy_names:
        synergy_s1 = [fo["value"] for fo in first_order
                      if fo["name"] in synergy_names]
        synergy_st = [to["value"] for to in total_order
                      if to["name"] in synergy_names]
        resource_s1 = [fo["value"] for fo in first_order
                       if fo["name"] in resource_names]
        resource_st = [to["value"] for to in total_order
                       if to["name"] in resource_names]

        x_pos = np.arange(2)
        width = 0.35
        ax.bar(x_pos - width / 2,
               [np.mean(synergy_s1), np.mean(resource_s1)],
               width, label='Avg S1', color=['#e74c3c', '#3498db'])
        ax.bar(x_pos + width / 2,
               [np.mean(synergy_st), np.mean(resource_st)],
               width, label='Avg ST', color=['#c0392b', '#2980b9'])
        ax.set_xticks(x_pos)
        ax.set_xticklabels(['Synergy Coefficients\n(alpha_pd, alpha_pc)',
                            'Resource Quantities\n(patrol, drones, cameras)'])
        ax.set_ylabel('Average Sobol Index')
        ax.set_title('Synergy vs Resource Quantity Sensitivity Comparison')
        ax.legend()

    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "synergy_vs_resource_comparison.png"),
                dpi=150)
    plt.close()

    print(f"Visualizations saved to {output_dir}")


def main():
    args = parse_args()
    workers = args.workers or os.cpu_count()

    print("=" * 60)
    print("Sobol Sensitivity Analysis - Synergy Coefficients")
    print("=" * 60)
    print(f"Base config: {args.base_config}")
    print(f"Num samples: {args.num_samples}")
    print(f"Output dir: {args.output_dir}")
    print(f"Vectorized: {args.vectorized}")
    print(f"GPU: {args.gpu}")
    print("=" * 60)

    with open(args.base_config, 'r', encoding='utf-8') as f:
        base_config = json.load(f)

    param_defs = parse_param_defs(args.params)
    param_names = [p["name"] for p in param_defs]
    print(f"Parameters: {param_names}")

    problem = {
        "num_vars": len(param_defs),
        "names": param_names,
        "bounds": [[p["min"], p["max"]] for p in param_defs]
    }

    if args.seed is not None:
        np.random.seed(args.seed)
    from SALib.sample import sobol as sobol_sample
    param_values = sobol_sample.sample(problem, args.num_samples)

    for i, name in enumerate(param_names):
        if name.startswith("alpha_"):
            pass
        else:
            param_values[:, i] = np.floor(param_values[:, i]).astype(int)

    total_evals = len(param_values)
    print(f"Total evaluations: {total_evals}")

    os.makedirs(args.output_dir, exist_ok=True)

    all_params = [
        {param_names[i]: float(param_values[j, i]) if param_names[i].startswith("alpha_")
         else int(param_values[j, i])
         for i in range(len(param_names))}
        for j in range(total_evals)
    ]

    # --- Checkpoint / resume ---
    ckpt_meta = {
        "num_samples": args.num_samples,
        "seed": args.seed,
        "param_defs": param_defs,
        "total_evals": total_evals,
    }

    completed_records: Dict[int, Dict] = {}
    if args.resume:
        saved_meta, completed_records = load_checkpoint(args.output_dir)
        if saved_meta is not None:
            if (saved_meta.get("num_samples") != args.num_samples or
                    saved_meta.get("seed") != args.seed or
                    saved_meta.get("total_evals") != total_evals):
                print("Warning: checkpoint parameters mismatch — starting fresh")
                completed_records = {}
            else:
                print(f"Resumed: {len(completed_records)}/{total_evals} evaluations already completed")

    pending_indices = [j for j in range(total_evals) if j not in completed_records]
    print(f"Pending: {len(pending_indices)} evaluations")

    start_time = time.time()

    if pending_indices and workers == 1:
        for idx, j in enumerate(pending_indices):
            print(f"[Eval {j + 1}/{total_evals}] ({idx + 1}/{len(pending_indices)} pending)",
                  end="\r")
            record = evaluate_model(base_config, all_params[j], j,
                                    args.output_dir, args.vectorized, args.gpu)
            completed_records[j] = record
            save_checkpoint(args.output_dir, ckpt_meta, completed_records)
    elif pending_indices:
        # Save base_config to temp file for workers (avoids passing 1MB+ dict per task)
        base_config_path = os.path.join(args.output_dir, "_base_config.json")
        with open(base_config_path, 'w', encoding='utf-8') as f:
            json.dump(base_config, f, ensure_ascii=False)

        from multiprocessing import get_context
        ctx = get_context('spawn')
        with ProcessPoolExecutor(max_workers=workers, mp_context=ctx, max_tasks_per_child=1) as executor:
            futures = {}
            for j in pending_indices:
                future = executor.submit(
                    _parallel_worker,
                    (base_config_path, all_params[j], j, args.output_dir,
                     args.vectorized, args.gpu)
                )
                futures[future] = j
            done = 0
            for future in as_completed(futures):
                done += 1
                record = future.result()
                completed_records[record["eval_idx"]] = record
                save_checkpoint(args.output_dir, ckpt_meta, completed_records)
                print(f"[Eval {done}/{len(pending_indices)} done] "
                      f"(total {len(completed_records)}/{total_evals})", end="\r")

    elapsed = time.time() - start_time
    eval_records = [completed_records[j] for j in range(total_evals)]
    eval_records.sort(key=lambda r: r["eval_idx"])

    successful = sum(1 for r in eval_records if r["success"])
    failed = total_evals - successful
    print(f"\nCompleted {total_evals} evaluations in {elapsed:.1f}s")
    print(f"Successful: {successful}, Failed: {failed}")

    output_array = np.array([r["best_fitness"] for r in eval_records])

    print("\nComputing Sobol indices...")
    sobol_indices = compute_sobol_indices(problem, output_array)

    print("\n--- Results ---")
    print(f"{'Parameter':<20} {'S1':>10} {'ST':>10} {'ST-S1':>10}")
    print("-" * 55)
    for fo, to in zip(sobol_indices["first_order"],
                      sobol_indices["total_order"]):
        interaction = to["value"] - fo["value"]
        print(f"{fo['name']:<20} {fo['value']:>10.4f} {to['value']:>10.4f} "
              f"{interaction:>10.4f}")

    if sobol_indices.get("second_order"):
        print(f"\n--- Second-order Interactions (top 10) ---")
        sorted_s2 = sorted(sobol_indices["second_order"],
                           key=lambda x: abs(x["value"]), reverse=True)
        for s2 in sorted_s2[:10]:
            print(f"  {s2['pair']:<35} S2={s2['value']:.4f} "
                  f"[{s2['conf_low']:.4f}, {s2['conf_high']:.4f}]")

    meta = {
        "base_config": os.path.abspath(args.base_config),
        "num_samples": args.num_samples,
        "total_evaluations": total_evals,
        "seed": args.seed,
        "workers": workers,
        "vectorized": args.vectorized,
        "use_gpu": args.gpu,
        "successful_evaluations": successful,
        "failed_evaluations": failed,
        "analysis_type": "synergy_coefficient_sensitivity"
    }

    with open(os.path.join(args.output_dir, "evaluations.json"), 'w',
              encoding='utf-8') as f:
        json.dump({"meta": meta, "evaluations": eval_records}, f, indent=2,
                  ensure_ascii=False)

    with open(os.path.join(args.output_dir, "sobol_synergy_indices.json"), 'w',
              encoding='utf-8') as f:
        json.dump({
            "meta": meta,
            "problem": {
                "num_vars": problem["num_vars"],
                "names": problem["names"],
                "bounds": problem["bounds"]
            },
            **sobol_indices
        }, f, indent=2, ensure_ascii=False)

    print(f"\nResults saved to {args.output_dir}")

    if successful >= 10:
        plot_synergy_sensitivity(sobol_indices, param_names, args.output_dir)

    print("\nAnalysis complete!")


if __name__ == "__main__":
    main()
