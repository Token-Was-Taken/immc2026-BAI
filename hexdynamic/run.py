"""
run.py — 一键运行：风险计算 + DSSA 优化 + 可视化

用法：
    python run.py input.json output.json
    python run.py input.json output.json --out_dir ./figures
    python run.py input.json output.json --vectorized --prefix day_dry
    python run.py input.json output.json --allow-partial-deployment
    python run.py input.json output.json --no-visualize   # 只跑优化，不生成图片
    python run.py output.json --visualize-only            # 只生成图片（已有 output JSON）
"""

import argparse
import os
import sys

# ---------------------------------------------------------------------------
# 复用已有模块
# ---------------------------------------------------------------------------
from protection_pipeline import run_pipeline
from visualize_output import load_data, plot_risk_heatmap, plot_risk_comparison, \
    plot_protection_heatmap, plot_terrain_map, plot_terrain_deployment_map, plot_species_map, plot_species_deployment_comparison, plot_protection_deployment_comparison


def visualize(output_path: str, input_path: str, out_dir: str, prefix: str):
    os.makedirs(out_dir, exist_ok=True)
    print(f"\n[VIZ] 加载数据: {output_path}")
    out, out_map, species_map, hex_size, boundary_xy = load_data(output_path, input_path)
    print(f"      网格数: {len(out['grids'])}, hex_size: {hex_size}")

    pre = prefix + "_" if prefix else ""

    def p(name):
        return os.path.join(out_dir, f"{pre}{name}")

    print("[VIZ] 生成图片...")
    plot_risk_heatmap(out, out_map, hex_size, boundary_xy,         save_path=p("risk_heatmap.png"))
    plot_risk_comparison(out, hex_size, boundary_xy,               save_path=p("risk_comparison.png"))
    plot_protection_heatmap(out, hex_size, boundary_xy,            save_path=p("protection_heatmap.png"))
    plot_terrain_map(out, hex_size, boundary_xy,                   save_path=p("terrain_map.png"))
    plot_terrain_deployment_map(out, hex_size, boundary_xy,        save_path=p("terrain_deployment_map.png"))
    plot_species_map(out, species_map, hex_size, boundary_xy,        save_path=p("species_map.png"))
    plot_species_deployment_comparison(out, species_map, hex_size, boundary_xy, save_path=p("species_deployment_comparison.png"))
    plot_protection_deployment_comparison(out, hex_size, boundary_xy, save_path=p("protection_deployment_comparison.png"))
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
    p.add_argument("input",  help="输入 JSON（pipeline 模式）或输出 JSON（--visualize-only 模式）")
    p.add_argument("output", nargs="?", default=None, help="输出 JSON 路径（pipeline 模式必填）")

    # pipeline 选项
    p.add_argument("--vectorized", action="store_true", default=False,
                   help="使用向量化覆盖模型（网格数 >1000 时推荐，速度提升 ~3-5x）")
    p.add_argument("--allow-partial-deployment", action="store_true", default=False,
                   help="允许优化器按边际收益决定是否部署资源（默认强制全量部署）")
    p.add_argument("--freeze-resources", type=str, default=None,
                   help="冻结资源列表，逗号分隔，如 'patrol,camera,drone'")

    # 可视化选项
    p.add_argument("--no-visualize", action="store_true", default=False,
                   help="只运行优化，不生成图片")
    p.add_argument("--visualize-only", action="store_true", default=False,
                   help="只生成图片，跳过优化（第一个位置参数视为 output JSON）")
    p.add_argument("--input", "-i", default=None,
                   help="pipeline 输入 JSON（--visualize-only 时用于物种数据）")
    p.add_argument("--out_dir", "-d", default="./figures", help="图片输出目录")
    p.add_argument("--prefix", default="", help="输出文件名前缀")

    return p.parse_args()


def main():
    args = parse_args()

    if args.visualize_only:
        # --visualize-only 模式：第一个位置参数 (args.input) 就是 output JSON
        output_json = args.input
        input_json  = args.output  # 可选，用于物种数据
        visualize(output_json, input_json, args.out_dir, args.prefix)
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
    )

    # Step 2: 可视化
    if not args.no_visualize:
        visualize(args.output, args.input, args.out_dir, args.prefix)


if __name__ == "__main__":
    main()
