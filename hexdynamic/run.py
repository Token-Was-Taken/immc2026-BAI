"""
run.py — 一键运行：风险计算 + DSSA 优化 + 可视化

用法：
    python run.py input.json output.json
    python run.py input.json output.json --out_dir ./figures
    python run.py input.json output.json --vectorized --prefix day_dry
    python run.py input.json output.json --allow-partial-deployment
    python run.py input.json output.json --no-visualize   # 只跑优化，不生成图片
    python run.py output.json --visualize-only            # 只生成图片（已有 output JSON）
    python run.py input.json output.json --only-best      # 只输出 best 变化的迭代
"""

import argparse
import json
import os
import sys

from protection_pipeline import run_pipeline
from visualize_output import load_data, plot_risk_heatmap, plot_risk_comparison, \
    plot_protection_heatmap, plot_terrain_map, plot_terrain_deployment_map, \
    plot_species_map, plot_species_deployment_comparison, plot_protection_deployment_comparison, \
    plot_fitness_history
from images_to_video import find_images, create_video, render_all_maps


def auto_grid_dpi(grids, max_grid_dpi=80):
    """
    根据地图网格数量自动计算合适的 grid_dpi，确保图片清晰且尺寸合理。
    grid_dpi 最大不超过 max_grid_dpi。
    """
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


def visualize(output_path: str, input_path: str, out_dir: str, prefix: str, grid_dpi: int = None, save_dpi: int = 150):
    os.makedirs(out_dir, exist_ok=True)
    print(f"\n[VIZ] 加载数据: {output_path}")
    out, out_map, species_map, hex_size, boundary_xy = load_data(output_path, input_path)
    if grid_dpi is None:
        grid_dpi = auto_grid_dpi(out["grids"])
    print(f"      网格数: {len(out['grids'])}, hex_size: {hex_size}")
    print(f"      grid_dpi: {grid_dpi} (auto), save_dpi: {save_dpi}")

    pre = prefix + "_" if prefix else ""

    def p(name):
        return os.path.join(out_dir, f"{pre}{name}")

    print("[VIZ] 生成图片...")
    plot_risk_heatmap(out, out_map, hex_size, boundary_xy,         save_path=p("risk_heatmap.png"), grid_dpi=grid_dpi, save_dpi=save_dpi)
    plot_risk_comparison(out, hex_size, boundary_xy,               save_path=p("risk_comparison.png"), grid_dpi=grid_dpi, save_dpi=save_dpi)
    plot_protection_heatmap(out, hex_size, boundary_xy,            save_path=p("protection_heatmap.png"), grid_dpi=grid_dpi, save_dpi=save_dpi)
    plot_terrain_map(out, hex_size, boundary_xy,                   save_path=p("terrain_map.png"), grid_dpi=grid_dpi, save_dpi=save_dpi)
    plot_terrain_deployment_map(out, hex_size, boundary_xy,        save_path=p("terrain_deployment_map.png"), grid_dpi=grid_dpi, save_dpi=save_dpi)
    plot_species_map(out, species_map, hex_size, boundary_xy,        save_path=p("species_map.png"), grid_dpi=grid_dpi, save_dpi=save_dpi)
    plot_species_deployment_comparison(out, species_map, hex_size, boundary_xy, save_path=p("species_deployment_comparison.png"), grid_dpi=grid_dpi, save_dpi=save_dpi)
    plot_protection_deployment_comparison(out, hex_size, boundary_xy, save_path=p("protection_deployment_comparison.png"), grid_dpi=grid_dpi, save_dpi=save_dpi)
    plot_fitness_history(out, save_path=p("fitness_history.png"), save_dpi=save_dpi)
    print(f"[VIZ] 完成，图片保存至: {out_dir}")


def parse_args():
    p = argparse.ArgumentParser(
        description="Protection Pipeline + Visualization",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog="""
示例:
  python run.py input.json output.json
  python run.py input.json output.json --vectorized --out_dir ./figures --prefix night_rainy
  python run.py input.json output.json --no-visualize
  python run.py output.json --visualize-only --input input.json
        """
    )
    p.add_argument("input",  help="Pipeline 模式：输入 JSON 路径 | Visualize-only 模式：输出 JSON 路径")
    p.add_argument("output", nargs="?", default=None, help="Pipeline 模式：输出 JSON 路径（必填）| Visualize-only 模式：忽略此参数，用 --input 指定输入 JSON")

    # pipeline 选项
    p.add_argument("--vectorized", action="store_true", default=False,
                   help="使用向量化覆盖模型（网格数 >1000 时推荐，速度提升 ~3-5x）")
    p.add_argument("--allow-partial-deployment", action="store_true", default=False,
                   help="允许优化器按边际收益决定是否部署资源（默认强制全量部署）")
    p.add_argument("--freeze-resources", type=str, default=None,
                   help="冻结资源列表，逗号分隔，如 'patrol,camera,drone'")
    p.add_argument("--max-iterations", type=int, default=None,
                   help="DSSA 最大迭代次数（默认：使用 input JSON 配置，若未配置则为 200）")
    p.add_argument("--warm-start", type=str, default=None, metavar="PATH",
                    help="热启动方案路径（提供已有的 output JSON 作为初始部署方案，加速收敛）")
    p.add_argument("--no-gpu", action="store_true", default=False,
                    help="禁用 GPU 加速（强制使用 CPU）")
    p.add_argument("--all-iters", action="store_true", default=False,
                    help="输出所有迭代（默认只输出 best_solution 变化的迭代）")

    # 可视化选项
    p.add_argument("--no-visualize", action="store_true", default=False,
                   help="只运行优化，不生成图片")
    p.add_argument("--visualize-only", action="store_true", default=False,
                   help="只生成图片，跳过优化（第一个位置参数视为 output JSON）")
    p.add_argument("--input", "-i", default=None,
                   help="pipeline 输入 JSON（--visualize-only 时用于物种数据）")
    p.add_argument("--out_dir", "-d", default="./figures", help="图片输出目录")
    p.add_argument("--prefix", default="", help="输出文件名前缀")
    p.add_argument("--grid_dpi", type=int, default=None,
                   help="每个六边形网格在输出图片中占用的像素宽度（默认根据地图大小自动计算，最大80）")
    p.add_argument("--dpi", type=int, default=150,
                   help="matplotlib savefig 的 DPI，控制输出图片的打印分辨率")

    return p.parse_args()


def main():
    args = parse_args()

    if args.visualize_only:
        # --visualize-only 模式：第一个位置参数 (args.input) 就是 output JSON
        output_json = args.input
        input_json  = args.output  # 可选，用于物种数据
        visualize(output_json, input_json, args.out_dir, args.prefix, grid_dpi=args.grid_dpi, save_dpi=args.dpi)
        return

    # 正常模式：需要 output 路径
    if args.output is None:
        print("错误: pipeline 模式需要提供 output 路径", file=sys.stderr)
        sys.exit(1)

    # 检查并创建输出目录
    output_dir = args.out_dir
    if output_dir:
        import os
        os.makedirs(output_dir, exist_ok=True)
        print(f"[DIR] 确保输出目录存在: {os.path.abspath(output_dir)}")

    output_path = args.output
    output_dir_for_output = os.path.dirname(output_path)
    if output_dir_for_output:
        import os
        os.makedirs(output_dir_for_output, exist_ok=True)
        print(f"[DIR] 确保输出 JSON 目录存在: {os.path.abspath(output_dir_for_output)}")

    # Step 1: 优化
    run_pipeline(
        input_path=args.input,
        output_path=args.output,
        vectorized=args.vectorized,
        allow_partial_deployment=args.allow_partial_deployment,
        freeze_resources=args.freeze_resources,
        out_dir=args.out_dir,
        max_iterations=args.max_iterations,
        warm_start_path=args.warm_start,
        use_gpu=not args.no_gpu,
        only_output_on_best_change=not args.all_iters,
    )

    # Step 2: 可视化
    if not args.no_visualize:
        visualize(args.output, args.input, args.out_dir, args.prefix, grid_dpi=args.grid_dpi, save_dpi=args.dpi)

    # Step 3: 如果启用了迭代可视化，自动生成迭代 deployment map 视频
    try:
        with open(args.input, 'r', encoding='utf-8') as f:
            input_data = json.load(f)
        dssa_cfg = input_data.get('dssa_config', {})
        if dssa_cfg.get('save_iteration_visualization', False):
            print(f"\n[VIDEO] 生成迭代部署地图视频...")
            image_paths = render_all_maps(args.out_dir, args.input, args.out_dir)
            if image_paths:
                video_path = os.path.join(args.out_dir, "iteration_deployment.mp4")
                create_video(image_paths, video_path, fps=5, resize_factor=1.0)
            else:
                print("\n[VIDEO] 未找到迭代部署地图图片，跳过视频生成")
    except Exception as e:
        print(f"\n[VIDEO] 视频生成失败: {e}")


if __name__ == "__main__":
    main()
