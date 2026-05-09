"""
batch_pipeline.py — 批量运行：对目录中多个 input JSON 依次执行 protection_pipeline + visualize_output

用法：
    python batch_pipeline.py --input-dir ./scenarios --output-dir ./results
    python batch_pipeline.py --input-dir ./scenarios --output-dir ./results --vectorized
    python batch_pipeline.py --input-dir ./scenarios --output-dir ./results --pattern "day_*.json"
    python batch_pipeline.py --input-dir ./scenarios --output-dir ./results --freeze-resources patrol,camera

输出结构：
    results/
    ├── scenario_1/
    │   ├── output.json
    │   ├── risk_heatmap.png
    │   ├── risk_comparison.png
    │   ├── protection_heatmap.png
    │   ├── terrain_map.png
    │   ├── terrain_deployment_map.png
    │   └── species_map.png
    ├── scenario_2/
    │   └── ...
    └── batch_summary.json
"""

import argparse
import os
import sys
import json
import glob
from datetime import datetime
from typing import List, Dict

import numpy as np


def scan_input_files(input_dir: str, pattern: str = "*.json") -> List[str]:
    files = sorted(glob.glob(os.path.join(input_dir, pattern)))
    files = [f for f in files if not os.path.basename(f).startswith("output_")]
    files = [f for f in files if not os.path.basename(f).startswith("temp_")]
    return files


def auto_grid_dpi(grids, max_grid_dpi=80):
    if not grids:
        return max_grid_dpi
    qs = {g["q"] for g in grids}
    rs = {g["r"] for g in grids}
    num_cols = len(qs)
    num_rows = len(rs)
    max_dim = max(num_cols, num_rows)
    if max_dim == 0:
        return max_grid_dpi
    target_max_pixels = 4000
    calculated = int(target_max_pixels / max_dim)
    calculated = max(calculated, 20)
    return min(calculated, max_grid_dpi)


def process_single(input_path: str, output_dir: str, prefix: str,
                   vectorized: bool, allow_partial: bool,
                   freeze_resources: str | None,
                   grid_dpi: int = None, save_dpi: int = 150) -> Dict:
    from protection_pipeline import run_pipeline
    from visualize_output import load_data, plot_risk_heatmap, plot_risk_comparison, \
        plot_protection_heatmap, plot_terrain_map, plot_terrain_deployment_map, plot_species_map, \
        plot_species_deployment_comparison, plot_protection_deployment_comparison, plot_fitness_history

    scenario_name = prefix or os.path.splitext(os.path.basename(input_path))[0]
    scenario_dir = os.path.join(output_dir, scenario_name)
    os.makedirs(scenario_dir, exist_ok=True)

    output_json = os.path.join(scenario_dir, "output.json")

    print(f"\n{'─'*60}")
    print(f"  [{scenario_name}] Input: {os.path.basename(input_path)}")
    print(f"  Output dir: {scenario_dir}")
    print(f"{'─'*60}")

    run_pipeline(
        input_path=input_path,
        output_path=output_json,
        vectorized=vectorized,
        allow_partial_deployment=allow_partial,
        freeze_resources=freeze_resources,
    )

    with open(output_json, "r", encoding="utf-8") as f:
        out = json.load(f)

    out_data, out_map, species_map, hex_size, boundary_xy = load_data(output_json, input_path)

    if grid_dpi is None:
        grid_dpi = auto_grid_dpi(out_data["grids"])

    pre = ""
    def p(name):
        return os.path.join(scenario_dir, f"{pre}{name}")

    print(f"  [VIZ] Generating figures ({len(out['grids'])} grids, grid_dpi={grid_dpi}, save_dpi={save_dpi})...")
    plot_risk_heatmap(out_data, out_map, hex_size, boundary_xy,         save_path=p("risk_heatmap.png"), grid_dpi=grid_dpi, save_dpi=save_dpi)
    plot_risk_comparison(out_data, hex_size, boundary_xy,               save_path=p("risk_comparison.png"), grid_dpi=grid_dpi, save_dpi=save_dpi)
    plot_protection_heatmap(out_data, hex_size, boundary_xy,            save_path=p("protection_heatmap.png"), grid_dpi=grid_dpi, save_dpi=save_dpi)
    plot_terrain_map(out_data, hex_size, boundary_xy,                   save_path=p("terrain_map.png"), grid_dpi=grid_dpi, save_dpi=save_dpi)
    plot_terrain_deployment_map(out_data, hex_size, boundary_xy,        save_path=p("terrain_deployment_map.png"), grid_dpi=grid_dpi, save_dpi=save_dpi)
    plot_species_map(out_map, species_map, hex_size, boundary_xy,       save_path=p("species_map.png"), grid_dpi=grid_dpi, save_dpi=save_dpi)
    plot_species_deployment_comparison(out_data, species_map, hex_size, boundary_xy, save_path=p("species_deployment_comparison.png"), grid_dpi=grid_dpi, save_dpi=save_dpi)
    plot_protection_deployment_comparison(out_data, hex_size, boundary_xy, save_path=p("protection_deployment_comparison.png"), grid_dpi=grid_dpi, save_dpi=save_dpi)
    plot_fitness_history(out_data, save_path=p("fitness_history.png"), save_dpi=save_dpi)

    summary = out.get("summary", {})
    return {
        "name": scenario_name,
        "input_file": os.path.basename(input_path),
        "output_dir": scenario_dir,
        "status": "success",
        "total_grids": summary.get("total_grids"),
        "total_risk": round(summary.get("total_risk", 0), 4),
        "best_fitness": round(summary.get("best_fitness", 0), 6),
        "total_protection_benefit": round(summary.get("total_protection_benefit", 0), 4),
        "average_protection_benefit": round(summary.get("average_protection_benefit", 0), 6),
        "resources_deployed": summary.get("resources_deployed", {}),
    }


def generate_batch_summary(results: List[Dict], output_dir: str):
    report = {
        "timestamp": datetime.now().isoformat(),
        "total_scenarios": len(results),
        "successful": sum(1 for r in results if r["status"] == "success"),
        "failed": sum(1 for r in results if r["status"] != "success"),
        "scenarios": results,
    }

    if results:
        fitness_values = [r["best_fitness"] for r in results if r["best_fitness"] is not None]
        pb_values = [r["total_protection_benefit"] for r in results if r["total_protection_benefit"] is not None]
        if fitness_values:
            report["fitness_stats"] = {
                "mean": round(float(np.mean(fitness_values)), 6),
                "std": round(float(np.std(fitness_values)), 6),
                "min": round(float(np.min(fitness_values)), 6),
                "max": round(float(np.max(fitness_values)), 6),
            }
        if pb_values:
            report["protection_benefit_stats"] = {
                "mean": round(float(np.mean(pb_values)), 4),
                "std": round(float(np.std(pb_values)), 4),
                "min": round(float(np.min(pb_values)), 4),
                "max": round(float(np.max(pb_values)), 4),
            }

    summary_path = os.path.join(output_dir, "batch_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n  Summary saved: {summary_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Batch Protection Pipeline: process multiple input JSON files through DSSA optimization + visualization.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog="""
Examples:
  python batch_pipeline.py --input-dir ./scenarios --output-dir ./results
  python batch_pipeline.py --input-dir ./scenarios --output-dir ./results --vectorized
  python batch_pipeline.py --input-dir ./scenarios --output-dir ./results --pattern "night_*.json"
  python batch_pipeline.py --input-dir ./scenarios --output-dir ./results --no-visualize
  python batch_pipeline.py --input-dir ./scenarios --output-dir ./results --freeze-resources patrol,camera

Output structure:
  output_dir/
  ├── scenario_name_1/
  │   ├── output.json
  │   ├── risk_heatmap.png
  │   ├── risk_comparison.png
  │   ├── protection_heatmap.png
  │   ├── terrain_map.png
  │   ├── terrain_deployment_map.png
  │   └── species_map.png
  ├── scenario_name_2/
  │   └── ...
  └── batch_summary.json
        """
    )
    parser.add_argument("--input-dir", "-i", required=True,
                        help="Directory containing input JSON files")
    parser.add_argument("--output-dir", "-o", default="./batch_results",
                        help="Output root directory (default: ./batch_results)")
    parser.add_argument("--pattern", "-p", default="*.json",
                        help="Glob pattern to match input files (default: *.json)")
    parser.add_argument("--vectorized", action="store_true", default=False,
                        help="Use vectorized coverage model (recommended for >1000 grids)")
    parser.add_argument("--allow-partial-deployment", action="store_true", default=False,
                        help="Allow optimizer to decide resource deployment by marginal benefit")
    parser.add_argument("--freeze-resources", type=str, default=None,
                        help="Comma-separated list of frozen resources (e.g., 'patrol,camera')")
    parser.add_argument("--no-visualize", action="store_true", default=False,
                        help="Skip visualization, only run optimization")
    parser.add_argument("--grid_dpi", type=int, default=None,
                        help="Per-grid pixel width in output images (default: auto-calculated, max 80)")
    parser.add_argument("--dpi", type=int, default=150,
                        help="matplotlib savefig DPI for output images")

    args = parser.parse_args()

    if not os.path.isdir(args.input_dir):
        print(f"Error: Input directory does not exist: {args.input_dir}", file=sys.stderr)
        sys.exit(1)

    input_files = scan_input_files(args.input_dir, args.pattern)
    if not input_files:
        print(f"Error: No JSON files matching '{args.pattern}' in {args.input_dir}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)

    print(f"{'='*60}")
    print(f"  BATCH PIPELINE")
    print(f"{'='*60}")
    print(f"  Input dir : {args.input_dir}")
    print(f"  Pattern   : {args.pattern}")
    print(f"  Files     : {len(input_files)}")
    print(f"  Output dir: {args.output_dir}")
    print(f"  Vectorized: {args.vectorized}")
    print(f"  Visualize : {not args.no_visualize}")
    print(f"{'='*60}")

    for f in input_files:
        print(f"    - {os.path.basename(f)}")

    results = []
    t_start = datetime.now()

    for idx, input_path in enumerate(input_files):
        print(f"\n[{idx+1}/{len(input_files)}]", end="")
        try:
            result = process_single(
                input_path=input_path,
                output_dir=args.output_dir,
                prefix="",
                vectorized=args.vectorized,
                allow_partial=args.allow_partial_deployment,
                freeze_resources=args.freeze_resources,
                grid_dpi=args.grid_dpi,
                save_dpi=args.dpi,
            )
            results.append(result)
            print(f"  OK  fitness={result['best_fitness']:.4f}  PB={result['total_protection_benefit']:.2f}")
        except Exception as e:
            print(f"  FAIL: {e}")
            results.append({
                "name": os.path.splitext(os.path.basename(input_path))[0],
                "input_file": os.path.basename(input_path),
                "status": f"error: {e}",
            })

    t_end = datetime.now()

    generate_batch_summary(results, args.output_dir)

    ok = sum(1 for r in results if r["status"] == "success")
    print(f"\n{'='*60}")
    print(f"  DONE  {ok}/{len(results)} successful  ({t_end - t_start})")
    print(f"  Output: {args.output_dir}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
