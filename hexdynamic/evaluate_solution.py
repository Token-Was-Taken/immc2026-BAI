"""
evaluate_solution.py - 使用 input JSON 和 output JSON 计算保护效益

用法:
    python evaluate_solution.py input.json output.json
    python evaluate_solution.py input.json output.json --vectorized
    python evaluate_solution.py input.json output.json --time-aware
    python evaluate_solution.py input.json output.json --per-grid
"""

import argparse
import json
import sys
import os
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))

from protection_pipeline import load_input, compute_risk_with_riskindex, build_data_loader
from grid_model import HexGridModel
from coverage_model import CoverageModel, DeploymentSolution
from coverage_model_vectorized import VectorizedCoverageModel


def load_solution_from_output(output_path: str) -> DeploymentSolution:
    with open(output_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    cameras = {}
    camps = {}
    drones = {}
    rangers = {}
    fences = {}

    for grid in data.get('grids', []):
        gid = grid['grid_id']
        dep = grid.get('deployment', {})
        if dep.get('camera', 0) > 0:
            cameras[gid] = dep['camera']
        if dep.get('drone', 0) > 0:
            drones[gid] = dep['drone']
        if dep.get('camp', 0) > 0:
            camps[gid] = dep['camp']
        if dep.get('patrol_rangers', 0) > 0:
            rangers[gid] = dep['patrol_rangers']
        fence_info = grid.get('fences', {})
        if fence_info and fence_info.get('fence_count', 0) > 0:
            for direction in fence_info.get('boundary_edge_list', []):
                fences[(gid, direction)] = 1

    return DeploymentSolution(
        cameras=cameras,
        camps=camps,
        drones=drones,
        rangers=rangers,
        fences=fences
    )


def build_coverage_model(input_path: str, vectorized: bool = False):
    data = load_input(input_path)
    risk_map, temporal_factor_map, raw_risk_map = compute_risk_with_riskindex(data)
    loader = build_data_loader(data, risk_map, temporal_factor_map)

    grid_model = HexGridModel(loader.grids)
    model_class = VectorizedCoverageModel if vectorized else CoverageModel
    coverage_model = model_class(
        grid_model,
        loader.coverage_params,
        loader.deployment_matrix,
        loader.visibility_params,
        loader.coverage_effectiveness
    )

    return coverage_model, grid_model, data


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate protection benefit of a deployment solution",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('input', help='Input JSON file (problem definition)')
    parser.add_argument('output', help='Output JSON file (deployment solution)')
    parser.add_argument('--vectorized', action='store_true',
                        help='Use vectorized coverage model (recommended for large maps)')
    parser.add_argument('--time-aware', action='store_true',
                        help='Calculate time-aware fitness')
    parser.add_argument('--per-grid', action='store_true',
                        help='Print per-grid protection benefit statistics')
    args = parser.parse_args()

    print(f"[1/3] Loading input: {args.input}")
    coverage_model, grid_model, data = build_coverage_model(args.input, args.vectorized)

    print(f"[2/3] Loading solution: {args.output}")
    solution = load_solution_from_output(args.output)

    print(f"[3/3] Computing protection metrics...")
    print(f"      Grids: {grid_model.get_grid_count()}")
    print(f"      Resources: cameras={sum(solution.cameras.values())}, "
          f"drones={sum(solution.drones.values())}, "
          f"camps={sum(solution.camps.values())}, "
          f"rangers={sum(solution.rangers.values())}, "
          f"fences={sum(1 for v in solution.fences.values() if v > 0)}")

    pb_per_grid = coverage_model.calculate_protection_benefit(solution)
    total_protection_benefit = sum(pb_per_grid.values())
    avg_protection_benefit = float(np.mean(list(pb_per_grid.values())))

    total_risk = 0.0
    for gid in grid_model.get_all_grid_ids():
        total_risk += grid_model.get_grid_risk(gid)

    if total_risk > 0:
        best_fitness = total_protection_benefit / total_risk
    else:
        best_fitness = 0.0

    if args.time_aware:
        total_risk_weighted = 0.0
        for gid in grid_model.get_all_grid_ids():
            total_risk_weighted += grid_model.get_grid_risk(gid) * grid_model.get_grid_temporal_factor(gid)
        if total_risk_weighted > 0:
            time_aware_fitness = total_protection_benefit / total_risk_weighted
        else:
            time_aware_fitness = 0.0

    print(f"\n{'=' * 60}")
    print(f"  Protection Benefit Evaluation Results")
    print(f"{'=' * 60}")
    print(f"  Total Protection Benefit : {total_protection_benefit:.6f}")
    print(f"  Average Protection Benefit: {avg_protection_benefit:.6f}")
    print(f"  Best Fitness             : {best_fitness:.6f}")
    print(f"  Total Risk               : {total_risk:.6f}")
    if args.time_aware:
        print(f"  Time-Aware Fitness       : {time_aware_fitness:.6f}")
        print(f"  Total Risk (Weighted)    : {total_risk_weighted:.6f}")

    output_summary = data.get('output', {}) if isinstance(data, dict) else {}
    if not output_summary:
        with open(args.output, 'r', encoding='utf-8') as f:
            out_data = json.load(f)
        output_summary = out_data.get('summary', {})

    if output_summary:
        orig_fitness = output_summary.get('best_fitness')
        orig_pb = output_summary.get('total_protection_benefit')
        orig_avg = output_summary.get('average_protection_benefit')
        if orig_fitness is not None:
            print(f"\n  --- Comparison with output JSON ---")
            print(f"  Original Best Fitness    : {orig_fitness:.6f}")
            print(f"  Recalculated Best Fitness: {best_fitness:.6f}")
            if abs(orig_fitness - best_fitness) > 1e-6:
                print(f"  [!] Fitness mismatch: delta = {abs(orig_fitness - best_fitness):.6e}")
            else:
                print(f"  [OK] Fitness matches")
            if orig_pb is not None:
                print(f"  Original Total PB        : {orig_pb:.6f}")
                print(f"  Recalculated Total PB    : {total_protection_benefit:.6f}")
                if abs(orig_pb - total_protection_benefit) > 1e-6:
                    print(f"  [!] Total PB mismatch: delta = {abs(orig_pb - total_protection_benefit):.6e}")
                else:
                    print(f"  [OK] Total PB matches")
            if orig_avg is not None:
                print(f"  Original Avg PB          : {orig_avg:.6f}")
                print(f"  Recalculated Avg PB      : {avg_protection_benefit:.6f}")

    if args.per_grid:
        pb_vals = list(pb_per_grid.values())
        print(f"\n  --- Per-Grid Protection Benefit ---")
        print(f"  Min  : {min(pb_vals):.6f}")
        print(f"  Max  : {max(pb_vals):.6f}")
        print(f"  Mean : {np.mean(pb_vals):.6f}")
        print(f"  Std  : {np.std(pb_vals):.6f}")
        print(f"  P25  : {np.percentile(pb_vals, 25):.6f}")
        print(f"  P50  : {np.percentile(pb_vals, 50):.6f}")
        print(f"  P75  : {np.percentile(pb_vals, 75):.6f}")
        print(f"  P95  : {np.percentile(pb_vals, 95):.6f}")

        zero_pb = sum(1 for v in pb_vals if v == 0.0)
        if zero_pb > 0:
            print(f"  Zero-benefit grids: {zero_pb} ({zero_pb / len(pb_vals) * 100:.1f}%)")

    print(f"\n{'=' * 60}")


if __name__ == '__main__':
    main()
