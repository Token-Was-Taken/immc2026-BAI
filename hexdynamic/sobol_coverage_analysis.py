"""
Sobol Sensitivity Analysis at Coverage Level

Instead of varying resource quantities, this script directly samples coverage
values (P_i, D_i, C_i) for each grid and computes Sobol indices for the
protection benefit formula. This isolates the mathematical interaction effects
in the protection effect model from the spatial deployment optimization.

Key insight: By removing the DSSA optimizer from the loop, we can measure the
pure mathematical sensitivity of the protection benefit to coverage interactions,
including the synergy terms alpha_pd * P*D/(1+P+D) and alpha_pc * P*C/(1+P+C).

Two analysis modes:
  1. Single-grid: Analyze one representative grid in detail
  2. Aggregate: Sample coverage for all grids, compute total benefit

Usage:
    python sobol_coverage_analysis.py <base_config.json> [options]

Example:
    python sobol_coverage_analysis.py base.json --num-samples 1024
    python sobol_coverage_analysis.py base.json --grid-id 5 --num-samples 2048
"""

import argparse
import json
import os
import sys
import copy
import numpy as np
from typing import Dict, List, Tuple, Any, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'hexdynamic'))

from SALib.sample import sobol as sobol_sample
from SALib.analyze import sobol
from data_loader import DataLoader, GridData, CoverageParameters
from grid_model import HexGridModel


def parse_args():
    parser = argparse.ArgumentParser(
        description="Sobol sensitivity analysis at coverage level"
    )
    parser.add_argument("base_config", help="Path to base input JSON configuration file")
    parser.add_argument("--num-samples", type=int, default=1024,
                        help="Base number of Saltelli samples (default: 1024)")
    parser.add_argument("--output-dir", type=str, default="./sobol_coverage_results",
                        help="Directory for outputs")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--grid-id", type=int, default=None,
                        help="Specific grid ID for single-grid analysis "
                             "(default: aggregate all grids)")
    parser.add_argument("--alpha-pd", type=float, default=0.4,
                        help="Patrol+Drone synergy coefficient (default: 0.4)")
    parser.add_argument("--alpha-pc", type=float, default=0.15,
                        help="Patrol+Camera synergy coefficient (default: 0.15)")
    parser.add_argument("--mode", choices=["single", "aggregate", "both"],
                        default="both",
                        help="Analysis mode: single-grid, aggregate, or both")
    return parser.parse_args()


def load_risk_map(base_config_path: str) -> Tuple[Dict[int, float], Dict[int, float], DataLoader]:
    with open(base_config_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    from protection_pipeline import compute_risk_with_riskindex, build_data_loader
    risk_map, temporal_factor_map, _ = compute_risk_with_riskindex(data)
    loader = build_data_loader(data, risk_map, temporal_factor_map)
    return risk_map, temporal_factor_map, loader


def compute_protection_benefit_from_coverage(
        P: np.ndarray, D: np.ndarray, C: np.ndarray,
        F: np.ndarray, risk: np.ndarray,
        params: CoverageParameters) -> np.ndarray:
    """
    Vectorized computation of protection benefit from coverage values.

    Args:
        P, D, C, F: Coverage arrays of shape (N,) or (N, num_grids)
        risk: Risk array of shape (num_grids,)
        params: Coverage parameters with weights and synergy coefficients

    Returns:
        Protection benefit array
    """
    base = (params.wp * P + params.wd * D + params.wc * C + params.wf * F)

    has_pd = (P > 0) | (D > 0)
    synergy_pd = np.where(has_pd,
                          params.alpha_pd * (P * D) / (1.0 + P + D), 0.0)

    has_pc = (P > 0) | (C > 0)
    synergy_pc = np.where(has_pc,
                          params.alpha_pc * (P * C) / (1.0 + P + C), 0.0)

    E = base + synergy_pd + synergy_pc
    benefit = risk * (1.0 - np.exp(-E))
    return benefit


def compute_total_benefit_from_coverage(
        P: np.ndarray, D: np.ndarray, C: np.ndarray,
        F: np.ndarray, risk: np.ndarray,
        params: CoverageParameters) -> np.ndarray:
    """
    Compute normalized total protection benefit.

    P, D, C, F: shape (N, num_grids)
    risk: shape (num_grids,)
    Returns: shape (N,)
    """
    benefit = compute_protection_benefit_from_coverage(P, D, C, F, risk, params)
    total_benefit = benefit.sum(axis=-1)
    total_risk = risk.sum()
    if total_risk > 0:
        total_benefit = total_benefit / total_risk
    return total_benefit


def single_grid_analysis(
        grid_id: int, risk: float, params: CoverageParameters,
        num_samples: int, seed: int, output_dir: str) -> Dict:
    """
    Sobol analysis for a single grid's protection benefit.

    Variables: P, D, C (coverage values for that grid)
    F is fixed at 0 (fence contribution is independent of coverage interaction).
    """
    print(f"\n{'=' * 60}")
    print(f"Single-grid analysis: grid_id={grid_id}, risk={risk:.4f}")
    print(f"{'=' * 60}")

    problem = {
        "num_vars": 3,
        "names": ["P", "D", "C"],
        "bounds": [[0.0, 1.0], [0.0, 1.0], [0.0, 1.0]]
    }

    if seed is not None:
        np.random.seed(seed)
    param_values = sobol_sample.sample(problem, num_samples)
    total_evals = len(param_values)

    P = param_values[:, 0]
    D = param_values[:, 1]
    C = param_values[:, 2]
    F = np.zeros(total_evals)
    risk_arr = np.full(total_evals, risk)

    output = compute_protection_benefit_from_coverage(P, D, C, F, risk_arr, params)

    Si = sobol.analyze(problem, output, num_resamples=1000)

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
            "conf_low": s1_val - s1_conf, "conf_high": s1_val + s1_conf
        })
        total_order.append({
            "name": name, "value": st_val,
            "conf_low": st_val - st_conf, "conf_high": st_val + st_conf
        })

    if "S2" in Si and Si["S2"] is not None:
        names = problem["names"]
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                s2_val = float(Si["S2"][i][j])
                s2_conf = float(Si["S2_conf"][i][j])
                if not np.isnan(s2_val):
                    second_order.append({
                        "pair": f"{names[i]} x {names[j]}",
                        "names": [names[i], names[j]],
                        "value": s2_val,
                        "conf_low": s2_val - s2_conf,
                        "conf_high": s2_val + s2_conf
                    })

    interaction_effects = []
    for fo, to in zip(first_order, total_order):
        interaction_effects.append({
            "name": fo["name"],
            "interaction_effect": max(0.0, to["value"] - fo["value"]),
            "first_order": fo["value"],
            "total_order": to["value"]
        })

    result = {
        "grid_id": grid_id,
        "risk": risk,
        "alpha_pd": params.alpha_pd,
        "alpha_pc": params.alpha_pc,
        "num_samples": num_samples,
        "total_evaluations": total_evals,
        "first_order": first_order,
        "total_order": total_order,
        "second_order": second_order,
        "interaction_effects": interaction_effects
    }

    print(f"\n{'Parameter':<10} {'S1':>10} {'ST':>10} {'ST-S1':>10}")
    print("-" * 45)
    for fo, to in zip(first_order, total_order):
        ie = to["value"] - fo["value"]
        print(f"{fo['name']:<10} {fo['value']:>10.4f} {to['value']:>10.4f} {ie:>10.4f}")

    if second_order:
        print(f"\nSecond-order interactions:")
        for s2 in second_order:
            print(f"  {s2['pair']:<15} S2={s2['value']:.4f} "
                  f"[{s2['conf_low']:.4f}, {s2['conf_high']:.4f}]")

    return result


def aggregate_analysis(
        risk_map: Dict[int, float], params: CoverageParameters,
        num_samples: int, seed: int, output_dir: str,
        grid_ids: List[int] = None) -> Dict:
    """
    Sobol analysis for total protection benefit across all grids.

    For each sample, we generate coverage values for ALL grids simultaneously,
    then compute the total (normalized) protection benefit.

    Variables: P, D, C (mean coverage across all grids)
    F is fixed at 0 to focus on the three-way interaction.
    """
    print(f"\n{'=' * 60}")
    print("Aggregate coverage-level Sobol analysis")
    print(f"{'=' * 60}")

    if grid_ids is None:
        grid_ids = sorted(risk_map.keys())
    num_grids = len(grid_ids)
    risk_arr = np.array([risk_map[gid] for gid in grid_ids])

    problem = {
        "num_vars": 3,
        "names": ["P", "D", "C"],
        "bounds": [[0.0, 1.0], [0.0, 1.0], [0.0, 1.0]]
    }

    if seed is not None:
        np.random.seed(seed)
    param_values = sobol_sample.sample(problem, num_samples)
    total_evals = len(param_values)

    P_flat = param_values[:, 0]
    D_flat = param_values[:, 1]
    C_flat = param_values[:, 2]

    P = np.tile(P_flat[:, np.newaxis], (1, num_grids))
    D = np.tile(D_flat[:, np.newaxis], (1, num_grids))
    C = np.tile(C_flat[:, np.newaxis], (1, num_grids))
    F = np.zeros((total_evals, num_grids))

    output = compute_total_benefit_from_coverage(P, D, C, F, risk_arr, params)

    Si = sobol.analyze(problem, output, num_resamples=1000)

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
            "conf_low": s1_val - s1_conf, "conf_high": s1_val + s1_conf
        })
        total_order.append({
            "name": name, "value": st_val,
            "conf_low": st_val - st_conf, "conf_high": st_val + st_conf
        })

    if "S2" in Si and Si["S2"] is not None:
        names = problem["names"]
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                s2_val = float(Si["S2"][i][j])
                s2_conf = float(Si["S2_conf"][i][j])
                if not np.isnan(s2_val):
                    second_order.append({
                        "pair": f"{names[i]} x {names[j]}",
                        "names": [names[i], names[j]],
                        "value": s2_val,
                        "conf_low": s2_val - s2_conf,
                        "conf_high": s2_val + s2_conf
                    })

    interaction_effects = []
    for fo, to in zip(first_order, total_order):
        interaction_effects.append({
            "name": fo["name"],
            "interaction_effect": max(0.0, to["value"] - fo["value"]),
            "first_order": fo["value"],
            "total_order": to["value"]
        })

    result = {
        "num_grids": num_grids,
        "alpha_pd": params.alpha_pd,
        "alpha_pc": params.alpha_pc,
        "num_samples": num_samples,
        "total_evaluations": total_evals,
        "first_order": first_order,
        "total_order": total_order,
        "second_order": second_order,
        "interaction_effects": interaction_effects
    }

    print(f"\n{'Parameter':<10} {'S1':>10} {'ST':>10} {'ST-S1':>10}")
    print("-" * 45)
    for fo, to in zip(first_order, total_order):
        ie = to["value"] - fo["value"]
        print(f"{fo['name']:<10} {fo['value']:>10.4f} {to['value']:>10.4f} {ie:>10.4f}")

    if second_order:
        print(f"\nSecond-order interactions:")
        for s2 in second_order:
            print(f"  {s2['pair']:<15} S2={s2['value']:.4f} "
                  f"[{s2['conf_low']:.4f}, {s2['conf_high']:.4f}]")

    return result


def multi_grid_analysis(
        risk_map: Dict[int, float], params: CoverageParameters,
        num_samples: int, seed: int, output_dir: str) -> Dict:
    """
    Per-grid Sobol analysis across all grids, then aggregate statistics.

    For each grid, independently compute Sobol indices of P, D, C
    on that grid's protection benefit. Then report summary statistics.
    """
    print(f"\n{'=' * 60}")
    print("Per-grid coverage-level Sobol analysis (all grids)")
    print(f"{'=' * 60}")

    grid_ids = sorted(risk_map.keys())

    problem = {
        "num_vars": 3,
        "names": ["P", "D", "C"],
        "bounds": [[0.0, 1.0], [0.0, 1.0], [0.0, 1.0]]
    }

    if seed is not None:
        np.random.seed(seed)
    param_values = sobol_sample.sample(problem, num_samples)
    total_evals = len(param_values)

    P = param_values[:, 0]
    D = param_values[:, 1]
    C = param_values[:, 2]
    F = np.zeros(total_evals)

    all_first_order = {"P": [], "D": [], "C": []}
    all_total_order = {"P": [], "D": [], "C": []}
    all_second_order = {"P x D": [], "P x C": [], "D x C": []}
    grid_results = []
    skipped_zero_risk = 0

    for grid_id in grid_ids:
        risk = risk_map[grid_id]

        if risk <= 0:
            skipped_zero_risk += 1
            continue

        risk_arr = np.full(total_evals, risk)
        output = compute_protection_benefit_from_coverage(P, D, C, F, risk_arr, params)

        if np.std(output) == 0:
            skipped_zero_risk += 1
            continue

        try:
            Si = sobol.analyze(problem, output, num_resamples=100)

            fo = {n: float(Si["S1"][i]) for i, n in enumerate(problem["names"])}
            to = {n: float(Si["ST"][i]) for i, n in enumerate(problem["names"])}

            has_nan = any(np.isnan(v) for v in list(fo.values()) + list(to.values()))
            if has_nan:
                skipped_zero_risk += 1
                continue

            for n in problem["names"]:
                all_first_order[n].append(fo[n])
                all_total_order[n].append(to[n])

            s2_dict = {}
            if "S2" in Si and Si["S2"] is not None:
                pair_idx = [(0, 1, "P x D"), (0, 2, "P x C"), (1, 2, "D x C")]
                for i, j, pair_name in pair_idx:
                    val = float(Si["S2"][i][j])
                    s2_dict[pair_name] = val
                    if not np.isnan(val):
                        all_second_order[pair_name].append(val)

            grid_results.append({
                "grid_id": grid_id, "risk": risk,
                "first_order": fo, "total_order": to,
                "second_order": s2_dict
            })
        except Exception:
            skipped_zero_risk += 1

    if skipped_zero_risk > 0:
        print(f"Skipped {skipped_zero_risk} grids with zero risk or zero-variance output")

    summary = {
        "num_grids_total": len(grid_ids),
        "num_grids_analyzed": len(grid_results),
        "num_grids_skipped": skipped_zero_risk,
        "alpha_pd": params.alpha_pd,
        "alpha_pc": params.alpha_pc,
        "num_samples": num_samples,
        "first_order_summary": {},
        "total_order_summary": {},
        "second_order_summary": {},
        "interaction_summary": {}
    }

    for n in ["P", "D", "C"]:
        vals_s1 = all_first_order[n]
        vals_st = all_total_order[n]
        arr_s1 = np.array(vals_s1) if vals_s1 else np.array([np.nan])
        arr_st = np.array(vals_st) if vals_st else np.array([np.nan])
        summary["first_order_summary"][n] = {
            "mean": float(np.nanmean(arr_s1)),
            "std": float(np.nanstd(arr_s1)),
            "min": float(np.nanmin(arr_s1)),
            "max": float(np.nanmax(arr_s1)),
            "median": float(np.nanmedian(arr_s1)),
            "count": int(np.sum(~np.isnan(arr_s1)))
        }
        summary["total_order_summary"][n] = {
            "mean": float(np.nanmean(arr_st)),
            "std": float(np.nanstd(arr_st)),
            "min": float(np.nanmin(arr_st)),
            "max": float(np.nanmax(arr_st)),
            "median": float(np.nanmedian(arr_st)),
            "count": int(np.sum(~np.isnan(arr_st)))
        }
        ie_vals = [st - s1 for s1, st in zip(vals_s1, vals_st)]
        arr_ie = np.array(ie_vals) if ie_vals else np.array([np.nan])
        summary["interaction_summary"][n] = {
            "mean": float(np.nanmean(arr_ie)),
            "std": float(np.nanstd(arr_ie)),
            "min": float(np.nanmin(arr_ie)),
            "max": float(np.nanmax(arr_ie)),
            "median": float(np.nanmedian(arr_ie))
        }

    for pair_name in ["P x D", "P x C", "D x C"]:
        vals = all_second_order[pair_name]
        if vals:
            arr = np.array(vals)
            summary["second_order_summary"][pair_name] = {
                "mean": float(np.nanmean(arr)),
                "std": float(np.nanstd(arr)),
                "min": float(np.nanmin(arr)),
                "max": float(np.nanmax(arr)),
                "median": float(np.nanmedian(arr)),
                "count": int(np.sum(~np.isnan(arr)))
            }

    print(f"\nAnalyzed {len(grid_results)} grids"
          f" (skipped {skipped_zero_risk} with zero risk/variance)")
    print(f"\n{'Parameter':<10} {'S1 mean':>10} {'ST mean':>10} {'ST-S1 mean':>12}")
    print("-" * 47)
    for n in ["P", "D", "C"]:
        s1_mean = summary["first_order_summary"][n]["mean"]
        st_mean = summary["total_order_summary"][n]["mean"]
        ie_mean = summary["interaction_summary"][n]["mean"]
        print(f"{n:<10} {s1_mean:>10.4f} {st_mean:>10.4f} {ie_mean:>12.4f}")

    print(f"\n{'Second-order':<15} {'S2 mean':>10} {'S2 median':>10} {'S2 max':>10}")
    print("-" * 50)
    for pair_name in ["P x D", "P x C", "D x C"]:
        if pair_name in summary["second_order_summary"]:
            s2s = summary["second_order_summary"][pair_name]
            print(f"{pair_name:<15} {s2s['mean']:>10.4f} {s2s['median']:>10.4f} "
                  f"{s2s['max']:>10.4f}")

    return {
        "summary": summary,
        "grid_results": grid_results
    }


def plot_coverage_sensitivity(results: Dict, output_dir: str, mode: str):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    if mode in ("single", "both") and "single_grid" in results:
        single = results["single_grid"]
        fig, axes = plt.subplots(1, 3, figsize=(18, 5))

        names = [fo["name"] for fo in single["first_order"]]
        s1 = [fo["value"] for fo in single["first_order"]]
        st = [to["value"] for to in single["total_order"]]
        x = np.arange(len(names))
        ax = axes[0]
        ax.bar(x - 0.15, s1, 0.3, label='S1', color='steelblue')
        ax.bar(x + 0.15, st, 0.3, label='ST', color='coral')
        ax.set_xticks(x)
        ax.set_xticklabels(names)
        ax.set_ylabel('Sobol Index')
        ax.set_title(f'Grid {single["grid_id"]}: S1 & ST')
        ax.legend()

        ax = axes[1]
        ie = [ie["interaction_effect"] for ie in single["interaction_effects"]]
        ie_names = [ie["name"] for ie in single["interaction_effects"]]
        ax.bar(ie_names, ie, color=['#2ecc71', '#e74c3c', '#3498db'])
        ax.set_ylabel('Interaction Effect (ST - S1)')
        ax.set_title(f'Grid {single["grid_id"]}: Interaction Effects')

        ax = axes[2]
        s2 = single.get("second_order", [])
        if s2:
            pairs = [s["pair"] for s in s2]
            vals = [s["value"] for s in s2]
            colors = ['#e74c3c' if 'P' in s["pair"] and ('D' in s["pair"] or 'C' in s["pair"])
                      else '#3498db' for s in s2]
            ax.bar(pairs, vals, color=colors)
            ax.set_ylabel('Second-order Index (S2)')
            ax.set_title(f'Grid {single["grid_id"]}: Second-order Interactions')
        else:
            ax.text(0.5, 0.5, 'No S2 data', ha='center', va='center',
                    transform=ax.transAxes)

        plt.suptitle(f'Coverage-level Sobol Analysis (alpha_pd={single["alpha_pd"]}, '
                     f'alpha_pc={single["alpha_pc"]})', fontsize=14)
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, "coverage_sobol_single_grid.png"),
                    dpi=150)
        plt.close()

    if mode in ("aggregate", "both") and "multi_grid" in results:
        multi = results["multi_grid"]
        summary = multi["summary"]

        fig, axes = plt.subplots(1, 3, figsize=(18, 5))

        # S1 distribution
        ax = axes[0]
        names = ["P", "D", "C"]
        s1_means = [summary["first_order_summary"][n]["mean"] for n in names]
        s1_stds = [summary["first_order_summary"][n]["std"] for n in names]
        ax.bar(names, s1_means, yerr=s1_stds, capsize=5, color='steelblue')
        ax.set_ylabel('First-order Index (S1)')
        ax.set_title('S1 Distribution Across Grids (mean ± std)')

        # ST distribution
        ax = axes[1]
        st_means = [summary["total_order_summary"][n]["mean"] for n in names]
        st_stds = [summary["total_order_summary"][n]["std"] for n in names]
        ax.bar(names, st_means, yerr=st_stds, capsize=5, color='coral')
        ax.set_ylabel('Total-order Index (ST)')
        ax.set_title('ST Distribution Across Grids (mean ± std)')

        # Interaction distribution
        ax = axes[2]
        ie_means = [summary["interaction_summary"][n]["mean"] for n in names]
        ie_stds = [summary["interaction_summary"][n]["std"] for n in names]
        ax.bar(names, ie_means, yerr=ie_stds, capsize=5, color='#2ecc71')
        ax.set_ylabel('Interaction Effect (ST - S1)')
        ax.set_title('Interaction Distribution Across Grids (mean ± std)')

        plt.suptitle(f'Per-grid Coverage Sobol Analysis (alpha_pd={summary["alpha_pd"]}, '
                     f'alpha_pc={summary["alpha_pc"]}, {summary["num_grids_analyzed"]} grids)',
                     fontsize=14)
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, "coverage_sobol_aggregate.png"),
                    dpi=150)
        plt.close()

        # Second-order heatmap across grids
        grid_results = multi.get("grid_results", [])
        if grid_results:
            s2_pd = [g["second_order"].get("P x D", 0.0) for g in grid_results]
            s2_pc = [g["second_order"].get("P x C", 0.0) for g in grid_results]
            s2_dc = [g["second_order"].get("D x C", 0.0) for g in grid_results]
            risks = [g["risk"] for g in grid_results]

            fig, ax = plt.subplots(figsize=(10, 6))
            ax.scatter(risks, s2_pd, alpha=0.6, label='P x D (synergy_pd)', color='#e74c3c')
            ax.scatter(risks, s2_pc, alpha=0.6, label='P x C (synergy_pc)', color='#3498db')
            ax.scatter(risks, s2_dc, alpha=0.6, label='D x C (no synergy)', color='#95a5a6')
            ax.set_xlabel('Grid Risk')
            ax.set_ylabel('Second-order Index (S2)')
            ax.set_title('Second-order Coverage Interactions vs Grid Risk')
            ax.legend()
            ax.axhline(y=0, color='gray', linestyle='--', linewidth=0.5)
            plt.tight_layout()
            plt.savefig(os.path.join(output_dir, "coverage_s2_vs_risk.png"),
                        dpi=150)
            plt.close()

    print(f"Visualizations saved to {output_dir}")


def main():
    args = parse_args()

    print("=" * 60)
    print("Sobol Sensitivity Analysis - Coverage Level")
    print("=" * 60)
    print(f"Base config: {args.base_config}")
    print(f"Num samples: {args.num_samples}")
    print(f"Mode: {args.mode}")
    print(f"alpha_pd: {args.alpha_pd}")
    print(f"alpha_pc: {args.alpha_pc}")
    print("=" * 60)

    print("\nLoading risk map from base config...")
    risk_map, temporal_factor_map, loader = load_risk_map(args.base_config)
    print(f"Loaded {len(risk_map)} grids")

    params = CoverageParameters(
        alpha_pd=args.alpha_pd,
        alpha_pc=args.alpha_pc
    )

    os.makedirs(args.output_dir, exist_ok=True)

    results_to_save = {}

    if args.mode in ("single", "both"):
        if args.grid_id is not None:
            grid_id = args.grid_id
            risk = risk_map.get(grid_id)
            if risk is None:
                print(f"Error: grid_id {grid_id} not found in risk map")
                return
        else:
            sorted_grids = sorted(risk_map.items(), key=lambda x: x[1], reverse=True)
            grid_id = sorted_grids[len(sorted_grids) // 2][0]
            risk = risk_map[grid_id]
            print(f"No grid_id specified, using median-risk grid: {grid_id} (risk={risk:.4f})")

        single_result = single_grid_analysis(
            grid_id, risk, params, args.num_samples, args.seed, args.output_dir)
        results_to_save["single_grid"] = single_result

    if args.mode in ("aggregate", "both"):
        multi_result = multi_grid_analysis(
            risk_map, params, args.num_samples, args.seed, args.output_dir)
        results_to_save["multi_grid"] = multi_result

    with open(os.path.join(args.output_dir, "sobol_coverage_results.json"), 'w',
              encoding='utf-8') as f:
        json.dump(results_to_save, f, indent=2, ensure_ascii=False,
                  default=lambda o: float(o) if isinstance(o, np.floating) else o)

    print(f"\nResults saved to {args.output_dir}")

    plot_coverage_sensitivity(results_to_save, args.output_dir, args.mode)

    print("\nAnalysis complete!")


if __name__ == "__main__":
    main()
