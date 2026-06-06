"""
run.py: one-command pipeline runner

Flow:
1) risk calculation + DSSA optimization
2) optional visualization
3) optional iteration deployment video

Examples:
    python run.py input.json output.json
    python run.py input.json output.json --out_dir ./figures
    python run.py input.json output.json --vectorized --prefix day_dry
    python run.py input.json output.json --allow-partial-deployment
    python run.py input.json output.json --no-visualize
    python run.py output.json --visualize-only
    python run.py input.json output.json --all-iters
"""

import argparse
import json
import os
import sys

from protection_pipeline import run_pipeline


def auto_grid_dpi(grids, max_grid_dpi=80):
    """Auto compute a reasonable grid DPI based on map dimensions."""
    if not grids:
        return max_grid_dpi
    qs = {g["q"] for g in grids}
    rs = {g["r"] for g in grids}
    max_dim = max(len(qs), len(rs))
    if max_dim == 0:
        return max_grid_dpi
    target_max_pixels = 4000
    calculated = int(target_max_pixels / max_dim)
    calculated = max(calculated, 20)
    return min(calculated, max_grid_dpi)


def visualize(output_path: str, input_path: str, out_dir: str, prefix: str, grid_dpi: int = None, save_dpi: int = 150):
    # Lazy import plotting stack so DSSA-only runs avoid heavy startup overhead.
    from visualize_output import (
        load_data,
        plot_risk_heatmap,
        plot_risk_comparison,
        plot_protection_heatmap,
        plot_terrain_map,
        plot_terrain_deployment_map,
        plot_species_map,
        plot_species_deployment_comparison,
        plot_protection_deployment_comparison,
        plot_fitness_history,
    )

    os.makedirs(out_dir, exist_ok=True)
    print(f"\n[VIZ] Loading data: output={output_path}, input={input_path}")
    input_data, output_data, grid_map, species_map, hex_size, boundary_xy = load_data(
        output_path=output_path, input_path=input_path
    )
    if grid_dpi is None:
        grid_dpi = auto_grid_dpi(input_data["grids"])
    print(f"      grids={len(input_data['grids'])}, hex_size={hex_size}")
    print(f"      grid_dpi={grid_dpi} (auto), save_dpi={save_dpi}")
    print(f"      output_data={'yes' if output_data else 'no (input-only visualizations)'}")

    pre = f"{prefix}_" if prefix else ""

    def p(name: str) -> str:
        return os.path.join(out_dir, f"{pre}{name}")

    print("[VIZ] Rendering images...")
    plot_risk_heatmap(
        input_data,
        grid_map,
        hex_size,
        boundary_xy,
        save_path=p("risk_heatmap.png"),
        output_data=output_data,
        risk_mode="normalized",
        grid_dpi=grid_dpi,
        save_dpi=save_dpi,
    )
    plot_risk_heatmap(
        input_data,
        grid_map,
        hex_size,
        boundary_xy,
        save_path=p("risk_heatmap_raw.png"),
        output_data=output_data,
        risk_mode="raw",
        grid_dpi=grid_dpi,
        save_dpi=save_dpi,
    )
    plot_terrain_map(
        input_data,
        hex_size,
        boundary_xy,
        save_path=p("terrain_map.png"),
        output_data=output_data,
        grid_dpi=grid_dpi,
        save_dpi=save_dpi,
    )
    plot_species_map(
        input_data,
        species_map,
        hex_size,
        boundary_xy,
        save_path=p("species_map.png"),
        grid_dpi=grid_dpi,
        save_dpi=save_dpi,
    )

    if output_data:
        plot_risk_comparison(
            output_data,
            hex_size,
            boundary_xy,
            save_path=p("risk_comparison.png"),
            grid_dpi=grid_dpi,
            save_dpi=save_dpi,
        )
        plot_protection_heatmap(
            output_data,
            hex_size,
            boundary_xy,
            save_path=p("protection_heatmap.png"),
            grid_dpi=grid_dpi,
            save_dpi=save_dpi,
        )
        plot_terrain_deployment_map(
            output_data,
            hex_size,
            boundary_xy,
            save_path=p("terrain_deployment_map.png"),
            grid_dpi=grid_dpi,
            save_dpi=save_dpi,
        )
        plot_species_deployment_comparison(
            output_data,
            species_map,
            hex_size,
            boundary_xy,
            save_path=p("species_deployment_comparison.png"),
            grid_dpi=grid_dpi,
            save_dpi=save_dpi,
        )
        plot_protection_deployment_comparison(
            output_data,
            hex_size,
            boundary_xy,
            save_path=p("protection_deployment_comparison.png"),
            grid_dpi=grid_dpi,
            save_dpi=save_dpi,
        )
        plot_fitness_history(output_data, save_path=p("fitness_history.png"), save_dpi=save_dpi)
    else:
        print("  [skip] Deployment/protection plots: missing output JSON")

    print(f"[VIZ] Done, images saved to: {out_dir}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Protection Pipeline + Visualization",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog="""
Examples:
  python run.py input.json output.json
  python run.py input.json output.json --vectorized --out_dir ./figures --prefix night_rainy
  python run.py input.json output.json --no-visualize
  python run.py output.json --visualize-only --input-json input.json
  python run.py --visualize-only --input-json input.json
        """,
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=None,
        help="Pipeline mode: input JSON path | visualize-only mode: optional output JSON path",
    )
    parser.add_argument(
        "output",
        nargs="?",
        default=None,
        help="Pipeline mode: output JSON path (required)",
    )

    # pipeline options
    parser.add_argument("--vectorized", action="store_true", default=False, help="Use vectorized coverage model")
    parser.add_argument(
        "--allow-partial-deployment",
        action="store_true",
        default=False,
        help="Allow optimizer to keep part of resources undeployed based on marginal benefit",
    )
    parser.add_argument("--freeze-resources", type=str, default=None, help="Frozen resources, comma-separated")
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="DSSA max iterations (default: input JSON config, fallback 200)",
    )
    parser.add_argument("--warm-start", type=str, default=None, metavar="PATH", help="Warm-start output JSON path")
    parser.add_argument("--no-gpu", action="store_true", default=False, help="Disable GPU acceleration")
    parser.add_argument(
        "--all-iters",
        action="store_true",
        default=False,
        help="Output every iteration (default only writes iterations where best changed)",
    )

    # visualization options
    parser.add_argument("--no-visualize", action="store_true", default=False, help="Skip image generation")
    parser.add_argument("--visualize-only", action="store_true", default=False, help="Only generate images")
    parser.add_argument("--input-json", "-i", default=None, dest="input_json", help="Input JSON for visualization")
    parser.add_argument(
        "--out_dir",
        "-d",
        default=None,
        help="Visualization output directory (if omitted, defaults to ./figures)",
    )
    parser.add_argument("--prefix", default="", help="Output filename prefix")
    parser.add_argument(
        "--grid_dpi",
        type=int,
        default=None,
        help="Approx pixels per hex in output image (auto if omitted)",
    )
    parser.add_argument("--dpi", type=int, default=150, help="matplotlib savefig DPI")

    return parser.parse_args()


def _resolve_viz_only_paths(args):
    """
    For visualize-only mode:
    - output JSON can be passed in positional `input` or `output`
    - input JSON for base layers comes from --input-json
    """
    if args.output:
        # Support legacy two-positional form:
        #   python run.py input.json output.json --visualize-only
        output_json = args.output
        input_json = args.input_json if args.input_json is not None else args.input
    else:
        # Single positional means that positional is output JSON.
        output_json = args.input
        input_json = args.input_json
    return output_json, input_json


def main():
    args = parse_args()
    viz_out_dir = args.out_dir or "./figures"

    if args.visualize_only:
        output_json, input_json = _resolve_viz_only_paths(args)
        if output_json is None and input_json is None:
            print("Error: --visualize-only requires output JSON or --input-json", file=sys.stderr)
            sys.exit(1)
        visualize(output_json, input_json, viz_out_dir, args.prefix, grid_dpi=args.grid_dpi, save_dpi=args.dpi)
        return

    # pipeline mode requires both input and output
    if args.input is None:
        print("Error: pipeline mode requires input JSON path", file=sys.stderr)
        sys.exit(1)
    if args.output is None:
        print("Error: pipeline mode requires output JSON path", file=sys.stderr)
        sys.exit(1)

    # Create visualization output directory only when needed.
    if (not args.no_visualize) or args.out_dir is not None:
        os.makedirs(viz_out_dir, exist_ok=True)
        print(f"[DIR] Ensure visualization output dir exists: {os.path.abspath(viz_out_dir)}")

    output_dir_for_output = os.path.dirname(args.output)
    if output_dir_for_output:
        os.makedirs(output_dir_for_output, exist_ok=True)
        print(f"[DIR] Ensure output JSON dir exists: {os.path.abspath(output_dir_for_output)}")

    run_pipeline(
        input_path=args.input,
        output_path=args.output,
        vectorized=args.vectorized,
        allow_partial_deployment=args.allow_partial_deployment,
        freeze_resources=args.freeze_resources,
        # Important: keep this None by default so input JSON dssa_config.output_dir is respected.
        out_dir=args.out_dir,
        max_iterations=args.max_iterations,
        warm_start_path=args.warm_start,
        use_gpu=not args.no_gpu,
        only_output_on_best_change=not args.all_iters,
    )

    if not args.no_visualize:
        visualize(args.output, args.input, viz_out_dir, args.prefix, grid_dpi=args.grid_dpi, save_dpi=args.dpi)

    # Iteration video generation is expensive for large grids; do it only when visualization is enabled.
    if not args.no_visualize:
        try:
            with open(args.input, "r", encoding="utf-8") as f:
                input_data = json.load(f)
            dssa_cfg = input_data.get("dssa_config", {})
            if dssa_cfg.get("save_iteration_visualization", False):
                # Iteration outputs may come from explicit CLI out_dir or JSON dssa_config.output_dir.
                iteration_input_dir = args.out_dir if args.out_dir is not None else dssa_cfg.get("output_dir")
                if not iteration_input_dir:
                    print("\n[VIDEO] Skip: save_iteration_visualization=true but output_dir is missing")
                    return
                if not os.path.isabs(iteration_input_dir):
                    iteration_input_dir = os.path.abspath(iteration_input_dir)
                print("\n[VIDEO] Generating iteration deployment video...")
                print(f"[VIDEO] Iteration input dir: {iteration_input_dir}")

                # Lazy import heavy rendering/video stack only when needed.
                from images_to_video import create_video, render_all_maps

                image_paths = render_all_maps(iteration_input_dir, args.input, viz_out_dir)
                if image_paths:
                    video_path = os.path.join(viz_out_dir, "iteration_deployment.mp4")
                    create_video(image_paths, video_path, fps=5, resize_factor=1.0)
                else:
                    print("\n[VIDEO] No iteration deployment maps found, skip video generation")
        except Exception as exc:
            print(f"\n[VIDEO] Video generation failed: {exc}")


if __name__ == "__main__":
    main()
