"""
evaluate_best.py - Wrapper script to evaluate DSSA best.json solutions

This script combines convert_best.py and evaluate_solution.py into a single workflow:
1. Converts best.json to evaluation format
2. Evaluates the converted solution

Usage:
    python evaluate_best.py input.json best.json
    python evaluate_best.py input.json figures/big/2/iteration_0000/best.json --vectorized
    python evaluate_best.py input.json best.json --time-aware --per-grid
"""

import argparse
import json
import sys
import os
import tempfile

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from convert_best import convert_best_to_eval_format
from evaluate_solution import build_coverage_model, load_solution_from_output


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate a DSSA best.json solution",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('input', help='Input JSON file (problem definition)')
    parser.add_argument('best', help='DSSA best.json file to evaluate')
    parser.add_argument('--vectorized', action='store_true',
                        help='Use vectorized coverage model (recommended for large maps)')
    parser.add_argument('--time-aware', action='store_true',
                        help='Calculate time-aware fitness')
    parser.add_argument('--per-grid', action='store_true',
                        help='Print per-grid protection benefit statistics')
    parser.add_argument('--output', '-o', default=None,
                        help='Optional output path for converted solution JSON')
    args = parser.parse_args()

    # Validate inputs
    if not os.path.exists(args.input):
        print(f"Error: Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(args.best):
        print(f"Error: Best file not found: {args.best}", file=sys.stderr)
        sys.exit(1)

    # Step 1: Convert best.json to evaluation format
    print(f"[1/3] Converting best.json: {args.best}")
    
    # Use temp file or specified output
    if args.output:
        converted_path = args.output
    else:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            converted_path = f.name
    
    convert_best_to_eval_format(args.input, args.best, converted_path)

    # Step 2: Load coverage model
    print(f"\n[2/3] Building coverage model: {args.input}")
    coverage_model, grid_model, data = build_coverage_model(args.input, args.vectorized)

    # Step 3: Load solution and evaluate
    print(f"[3/3] Evaluating solution...")
    solution = load_solution_from_output(converted_path)

    print(f"      Grids: {grid_model.get_grid_count()}")
    print(f"      Resources: cameras={sum(solution.cameras.values())}, "
          f"drones={sum(solution.drones.values())}, "
          f"camps={sum(solution.camps.values())}, "
          f"rangers={sum(solution.rangers.values())}, "
          f"fences={sum(1 for v in solution.fences.values() if v > 0)}")

    import numpy as np
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

    # Load original statistics from best.json if available
    with open(args.best, 'r', encoding='utf-8') as f:
        best_data = json.load(f)
    original_stats = best_data.get('statistics', {})
    
    if original_stats:
        orig_fitness = original_stats.get('best_fitness')
        if orig_fitness is not None:
            print(f"\n  --- Comparison with original best.json ---")
            print(f"  Original Best Fitness    : {orig_fitness:.6f}")
            print(f"  Recalculated Best Fitness: {best_fitness:.6f}")
            if abs(orig_fitness - best_fitness) > 1e-6:
                print(f"  [!] Fitness mismatch: delta = {abs(orig_fitness - best_fitness):.6e}")
            else:
                print(f"  [OK] Fitness matches")

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

    # Cleanup temp file if not specified by user
    if not args.output and os.path.exists(converted_path):
        os.unlink(converted_path)


if __name__ == '__main__':
    main()
