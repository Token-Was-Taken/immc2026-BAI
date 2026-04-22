"""
visualize_iterations.py

Standalone script: takes an iterations output directory and generates
visualizations for all solutions across all iterations.

Usage:
    python visualize_iterations.py <iterations_dir> --input <input.json>
    python visualize_iterations.py ./output_results/iterations --input sensitivity/base.json
    python visualize_iterations.py ./output_results/iterations --input sensitivity/base.json \\
        --final-output ./output_results/final_output.json \\
        --out-dir ./output_results/figures \\
        --workers 8

Steps performed:
    1. Postprocess each iteration_XXXX dir → visualization JSON files
    2. Compute global PB vmaxes across all solutions in each iteration
    3. Generate heatmaps (terrain, risk comparison, protection normalized + raw)
"""

import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

from postprocess_iteration import postprocess_iteration


# ---------------------------------------------------------------------------
# Global vmax computation
# ---------------------------------------------------------------------------

def compute_global_vmaxes(viz_dir: str) -> tuple:
    """Scan all JSON files under a single viz dir and return (norm_vmax, raw_vmax)."""
    norm_vmax = 0.0
    raw_vmax = 0.0
    for fname in os.listdir(viz_dir):
        if not fname.endswith('.json'):
            continue
        try:
            with open(os.path.join(viz_dir, fname), 'r', encoding='utf-8') as f:
                data = json.load(f)
            for g in data.get('grids', []):
                norm_vmax = max(norm_vmax, g.get('protection_benefit_normalized', 0))
                raw_vmax  = max(raw_vmax,  g.get('protection_benefit_raw', 0))
        except Exception:
            pass
    return norm_vmax or 1.0, raw_vmax or 1.0


def compute_all_iterations_vmaxes(viz_base_dir: str, iter_names: list) -> tuple:
    """Scan all JSON files across all iteration viz dirs to get a single global vmax."""
    norm_vmax = 0.0
    raw_vmax = 0.0
    print("Computing global PB vmax across all iterations...")
    for iter_name in iter_names:
        iter_viz = os.path.join(viz_base_dir, iter_name)
        if not os.path.isdir(iter_viz):
            continue
        n, r = compute_global_vmaxes(iter_viz)
        norm_vmax = max(norm_vmax, n)
        raw_vmax  = max(raw_vmax,  r)
    norm_vmax = norm_vmax or 1.0
    raw_vmax  = raw_vmax  or 1.0
    print(f"  Global vmax — normalized: {norm_vmax:.4f}, raw: {raw_vmax:.4f}")
    return norm_vmax, raw_vmax


# ---------------------------------------------------------------------------
# Single-file visualization worker (runs in subprocess)
# ---------------------------------------------------------------------------

def _visualize_one(args_tuple):
    json_path, input_path, out_dir, pb_norm_vmax, pb_raw_vmax = args_tuple
    from visualize_iteration import main as viz_main
    import matplotlib
    matplotlib.use('Agg')

    original_argv = sys.argv
    try:
        sys.argv = [
            'visualize_iteration.py', json_path,
            '--input', input_path,
            '--out_dir', out_dir,
            '--pb-norm-vmax', str(pb_norm_vmax),
            '--pb-raw-vmax',  str(pb_raw_vmax),
        ]
        viz_main()
        return True
    except Exception as e:
        print(f"Warning: Failed to visualize {json_path}: {e}")
        return False
    finally:
        sys.argv = original_argv


# ---------------------------------------------------------------------------
# Per-iteration visualization
# ---------------------------------------------------------------------------

def visualize_iteration_dir(iter_viz_dir: str, input_path: str,
                             iter_name: str, figures_dir: str,
                             max_workers: int,
                             pb_norm_vmax: float, pb_raw_vmax: float):
    json_files = sorted([f for f in os.listdir(iter_viz_dir) if f.endswith('.json')])
    if not json_files:
        print(f"  [{iter_name}] No JSON files, skipping")
        return

    print(f"  [{iter_name}] {len(json_files)} solutions | "
          f"PB vmax norm={pb_norm_vmax:.4f} raw={pb_raw_vmax:.4f}")

    tasks = []
    for fname in json_files:
        json_path = os.path.join(iter_viz_dir, fname)
        out_dir   = os.path.join(figures_dir, iter_name, fname.replace('.json', ''))
        os.makedirs(out_dir, exist_ok=True)
        tasks.append((json_path, input_path, out_dir, pb_norm_vmax, pb_raw_vmax))

    with ProcessPoolExecutor(max_workers=min(max_workers, multiprocessing.cpu_count())) as ex:
        futures = {ex.submit(_visualize_one, t): t for t in tasks}
        done = 0
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception:
                pass
            done += 1
            if done % 10 == 0 or done == len(tasks):
                print(f"    {done}/{len(tasks)} done")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="Generate visualizations from DSSA iteration output directory",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument('iterations_dir',
                   help="Path to iterations directory (e.g. output_results/iterations)")
    p.add_argument('--input', '-i', required=True,
                   help="Original input JSON (used for grid metadata)")
    p.add_argument('--final-output', '-f', default=None,
                   help="Path to final_output.json for risk data (optional but recommended)")
    p.add_argument('--viz-dir', default=None,
                   help="Where to write postprocessed visualization JSONs "
                        "(default: <iterations_dir>/../visualization)")
    p.add_argument('--out-dir', '-o', default=None,
                   help="Where to write figure PNGs "
                        "(default: <iterations_dir>/../figures)")
    p.add_argument('--workers', '-w', type=int, default=4,
                   help="Parallel worker processes for visualization")
    p.add_argument('--skip-postprocess', action='store_true',
                   help="Skip postprocessing step (use existing viz JSONs)")
    p.add_argument('--iterations', nargs='*', default=None,
                   help="Only process specific iterations, e.g. --iterations iteration_0000 iteration_0001")
    return p.parse_args()


def main():
    args = parse_args()

    iterations_dir = os.path.abspath(args.iterations_dir)
    input_path     = os.path.abspath(args.input)
    parent_dir     = os.path.dirname(iterations_dir)

    viz_base_dir = os.path.abspath(args.viz_dir)  if args.viz_dir  else os.path.join(parent_dir, 'visualization')
    figures_dir  = os.path.abspath(args.out_dir)  if args.out_dir  else os.path.join(parent_dir, 'figures')
    final_output = os.path.abspath(args.final_output) if args.final_output else None

    os.makedirs(viz_base_dir, exist_ok=True)
    os.makedirs(figures_dir,  exist_ok=True)

    # Discover iteration directories
    all_iter_dirs = sorted([
        d for d in os.listdir(iterations_dir)
        if os.path.isdir(os.path.join(iterations_dir, d))
    ])
    if args.iterations:
        all_iter_dirs = [d for d in all_iter_dirs if d in args.iterations]

    if not all_iter_dirs:
        print("No iteration directories found. Exiting.")
        sys.exit(1)

    print(f"Found {len(all_iter_dirs)} iteration(s) to process")
    print(f"Input JSON  : {input_path}")
    print(f"Viz JSON dir: {viz_base_dir}")
    print(f"Figures dir : {figures_dir}")
    print(f"Workers     : {args.workers}")
    print()

    # -----------------------------------------------------------------------
    # Step 1: Postprocess
    # -----------------------------------------------------------------------
    if not args.skip_postprocess:
        print("=" * 60)
        print("Step 1: Postprocessing iteration results")
        print("=" * 60)
        for iter_name in all_iter_dirs:
            iter_full = os.path.join(iterations_dir, iter_name)
            iter_viz  = os.path.join(viz_base_dir, iter_name)
            print(f"  Postprocessing {iter_name}...")
            try:
                postprocess_iteration(iter_full, input_path, iter_viz,
                                      final_output_path=final_output)
            except Exception as e:
                print(f"  Warning: {iter_name} postprocess failed: {e}")
    else:
        print("Skipping postprocess (--skip-postprocess)")

    # -----------------------------------------------------------------------
    # Step 2: Visualize
    # -----------------------------------------------------------------------
    print()
    print("=" * 60)
    print("Step 2: Computing global PB vmax across all iterations")
    print("=" * 60)
    pb_norm_vmax, pb_raw_vmax = compute_all_iterations_vmaxes(viz_base_dir, all_iter_dirs)

    print()
    print("=" * 60)
    print("Step 3: Generating visualizations")
    print("=" * 60)
    for iter_name in all_iter_dirs:
        iter_viz = os.path.join(viz_base_dir, iter_name)
        if not os.path.isdir(iter_viz):
            print(f"  [{iter_name}] viz dir not found, skipping")
            continue
        visualize_iteration_dir(iter_viz, input_path, iter_name,
                                figures_dir, args.workers,
                                pb_norm_vmax, pb_raw_vmax)

    print()
    print("Done. Figures saved to:", figures_dir)


if __name__ == '__main__':
    main()
