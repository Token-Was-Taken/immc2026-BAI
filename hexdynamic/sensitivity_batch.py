"""
多资源敏感性分析批处理脚本

串行遍历每种资源，逐个调用 sensitivity_analysis.py（资源内并行）。
分析完成后直接生成 sensitivity_report 风格的可视化报告。

用法：
    python sensitivity_batch.py --input base.json \
        --ranges patrol:0:50:5 camera:0:400:10 drone:0:20:1 \
        --workers 4 --vectorized

    # 两步法（粗扫后自动细扫饱和区）
    python sensitivity_batch.py --input base.json \
        --ranges camera:0:400:50 \
        --workers 4 --two-step --vectorized

    # 跳过报告生成
    python sensitivity_batch.py --input base.json --no-report
"""

import argparse
import json
import os
import sys
import time
import subprocess
import shutil
import glob as glob_module
from typing import Dict, List, Tuple, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np


DEFAULT_RANGES = {
    "patrol": (0, 50, 5),
    "camera": (0, 20, 2),
    "drone": (0, 10, 1),
    "camp": (0, 5, 1),
    "fence": (0, 100, 10),
}

RESOURCE_LABEL = {
    "camera":  "Camera Count",
    "drone":   "Drone Count",
    "patrol":  "Patrol Count",
    "camp":    "Camp Count",
    "fence":   "Fence Length",
}

COLORS = {
    "benefit":  "#2ca02c",
    "fitness":  "#1f77b4",
    "marginal": "#ff7f0e",
    "gain":     "#9467bd",
    "sat_line": "#d62728",
}


def parse_ranges(ranges_input: Optional[List[str]]) -> Dict[str, Tuple[int, int, int]]:
    result = {}
    if ranges_input is None:
        return dict(DEFAULT_RANGES)
    for item in ranges_input:
        parts = item.split(":")
        if len(parts) != 4:
            raise ValueError(
                f"Invalid range format '{item}', expected resource:min:max:step"
            )
        name = parts[0].strip().lower()
        min_val, max_val, step = int(parts[1]), int(parts[2]), int(parts[3])
        if min_val < 0 or max_val < min_val or step <= 0:
            raise ValueError(
                f"Invalid range values for '{name}': min={min_val}, max={max_val}, step={step}"
            )
        result[name] = (min_val, max_val, step)
    return result


def run_single_resource(input_path: str, resource: str, range_tuple: Tuple[int, int, int],
                        output_dir: str, vectorized: bool, workers: int,
                        two_step: bool, fine_step_ratio: int,
                        warm_start: bool = False, warm_start_groups: int = None,
                        no_cache: bool = False) -> dict:
    min_val, max_val, step = range_tuple
    cmd = [
        sys.executable,
        os.path.join(os.path.dirname(__file__), "sensitivity_analysis.py"),
        "--input", input_path,
        "--resource", resource,
        "--range", str(min_val), str(max_val), str(step),
        "--output", output_dir,
        "--workers", str(workers),
    ]
    if vectorized:
        cmd.append("--vectorized")
    if two_step:
        cmd.append("--two-step")
        cmd.extend(["--fine-step-ratio", str(fine_step_ratio)])
    if warm_start:
        cmd.append("--warm-start")
    if warm_start_groups and warm_start_groups > 1:
        cmd.extend(["--warm-start-groups", str(warm_start_groups)])
    if no_cache:
        cmd.append("--no-cache")

    print(f"\n[START] {resource}: range={min_val}-{max_val}, step={step}, workers={workers}")
    start = time.time()
    try:
        result = subprocess.run(cmd, text=True)
        elapsed = time.time() - start
        if result.returncode != 0:
            print(f"[FAIL]  {resource}: error after {elapsed:.1f}s")
            return {"resource": resource, "success": False, "error": "non-zero exit code", "elapsed": elapsed}
        print(f"[DONE]  {resource}: completed in {elapsed:.1f}s")
        return {"resource": resource, "success": True, "elapsed": elapsed}
    except Exception as e:
        elapsed = time.time() - start
        print(f"[FAIL]  {resource}: exception after {elapsed:.1f}s - {e}")
        return {"resource": resource, "success": False, "error": str(e), "elapsed": elapsed}


def _compute_metrics(data: dict):
    results = data["results"]
    if not results:
        return None

    res_values = [r["resource_value"] for r in results]
    benefits = [r["total_protection_benefit"] for r in results]
    fitnesses = [r["best_fitness"] for r in results]

    marginal = [0.0]
    for i in range(1, len(benefits)):
        dv = res_values[i] - res_values[i - 1]
        marginal.append((benefits[i] - benefits[i - 1]) / dv if dv else 0.0)

    max_mb = max(marginal[1:]) if len(marginal) > 1 else 0
    saturation_idx = next(
        (i for i in range(1, len(marginal)) if marginal[i] < max_mb * 0.05),
        len(marginal) - 1
    )
    saturation_value = res_values[saturation_idx]

    base = benefits[0] if benefits[0] > 0 else 1e-9
    gain_pct = [(b - benefits[0]) / base * 100 for b in benefits]

    return {
        "res_values":       res_values,
        "benefits":         benefits,
        "fitnesses":        fitnesses,
        "marginal":         marginal,
        "saturation_idx":   saturation_idx,
        "saturation_value": saturation_value,
        "gain_pct":         gain_pct,
    }


def _xlabel(res_type: str) -> str:
    return RESOURCE_LABEL.get(res_type.lower(), f"{res_type.capitalize()} Count")


def _plot_report(data: dict, metrics: dict, out_path: str):
    res_type = data["resource_type"]
    m = metrics
    rv = m["res_values"]
    sat = m["saturation_value"]
    sat_i = m["saturation_idx"]

    n = len(rv)
    step = max(1, n // 20)
    indices = list(range(0, n, step))
    if indices[-1] != n - 1:
        indices.append(n - 1)
    if sat_i not in indices:
        indices.append(sat_i)
        indices.sort()
    n_rows = len(indices)

    chart_h = 8.0
    table_h = max(2.5, n_rows * 0.28 + 0.8)
    total_h = chart_h + table_h + 0.6

    fig = plt.figure(figsize=(16, total_h))
    fig.suptitle(
        f"Sensitivity Analysis Report: {res_type.upper()}",
        fontsize=15, fontweight="bold", y=1.0 - 0.3 / total_h
    )

    chart_ratio = chart_h / (chart_h + table_h)
    table_ratio = table_h / (chart_h + table_h)

    gs = gridspec.GridSpec(
        2, 1,
        figure=fig,
        height_ratios=[chart_ratio, table_ratio],
        hspace=0.08,
        left=0.06, right=0.97,
        top=1.0 - 0.5 / total_h,
        bottom=0.02,
    )

    gs_charts = gridspec.GridSpecFromSubplotSpec(
        2, 2, subplot_spec=gs[0], hspace=0.45, wspace=0.35
    )

    ax1 = fig.add_subplot(gs_charts[0, 0])
    ax1.plot(rv, m["benefits"], "o-", lw=2, ms=5, color=COLORS["benefit"])
    ax1.axvline(sat, color=COLORS["sat_line"], ls="--", lw=1.2, label=f"Saturation @ {sat}")
    ax1.set_xlabel(_xlabel(res_type), fontsize=10)
    ax1.set_ylabel("Total Protection Benefit", fontsize=10)
    ax1.set_title("Protection Benefit", fontsize=11, fontweight="bold")
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)

    ax2 = fig.add_subplot(gs_charts[0, 1])
    ax2.plot(rv, m["fitnesses"], "s-", lw=2, ms=5, color=COLORS["fitness"])
    ax2.axvline(sat, color=COLORS["sat_line"], ls="--", lw=1.2, label=f"Saturation @ {sat}")
    ax2.set_xlabel(_xlabel(res_type), fontsize=10)
    ax2.set_ylabel("Best Fitness", fontsize=10)
    ax2.set_title("Best Fitness", fontsize=11, fontweight="bold")
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3)

    ax3 = fig.add_subplot(gs_charts[1, 0])
    bar_w = max(1, (max(rv) - min(rv)) / len(rv) * 0.7)
    ax3.bar(rv, m["marginal"], width=bar_w, color=COLORS["marginal"], alpha=0.75,
            label="Marginal Benefit")
    ax3.axvline(sat, color=COLORS["sat_line"], ls="--", lw=1.2, label=f"Saturation @ {sat}")
    ax3.axhline(0, color="black", lw=0.5)
    ax3.set_xlabel(_xlabel(res_type), fontsize=10)
    ax3.set_ylabel("Marginal Benefit / Unit", fontsize=10)
    ax3.set_title("Marginal Benefit", fontsize=11, fontweight="bold")
    ax3.legend(fontsize=8)
    ax3.grid(True, alpha=0.3, axis="y")

    ax4 = fig.add_subplot(gs_charts[1, 1])
    ax4.plot(rv, m["gain_pct"], "D-", lw=2, ms=5, color=COLORS["gain"])
    ax4.axvline(sat, color=COLORS["sat_line"], ls="--", lw=1.2, label=f"Saturation @ {sat}")
    ax4.set_xlabel(_xlabel(res_type), fontsize=10)
    ax4.set_ylabel("Benefit Gain vs Baseline (%)", fontsize=10)
    ax4.set_title("Cumulative Gain over Baseline", fontsize=11, fontweight="bold")
    ax4.legend(fontsize=8)
    ax4.grid(True, alpha=0.3)

    ax5 = fig.add_subplot(gs[1])
    ax5.axis("off")

    col_labels = [_xlabel(res_type), "Total Benefit", "Best Fitness",
                  "Marginal Benefit", "Gain vs Baseline (%)"]
    rows = []
    for i in indices:
        rows.append([
            str(rv[i]),
            f"{m['benefits'][i]:.4f}",
            f"{m['fitnesses'][i]:.4f}",
            f"{m['marginal'][i]:.4f}",
            f"{m['gain_pct'][i]:.1f}%",
        ])

    tbl = ax5.table(
        cellText=rows,
        colLabels=col_labels,
        cellLoc="center",
        loc="upper center",
        colWidths=[0.14, 0.18, 0.16, 0.18, 0.20],
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.scale(1, 1.4)

    for j in range(len(col_labels)):
        cell = tbl[(0, j)]
        cell.set_facecolor("#2c7bb6")
        cell.set_text_props(color="white", fontweight="bold")

    for row_idx, data_idx in enumerate(indices):
        bg = "#fff9c4" if data_idx == sat_i else ("#f5f5f5" if row_idx % 2 == 0 else "white")
        for j in range(len(col_labels)):
            tbl[(row_idx + 1, j)].set_facecolor(bg)

    ax5.set_title(
        f"Key Data Points  (saturation row highlighted in yellow, step={step})",
        fontsize=9, pad=4, loc="left"
    )

    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved: {out_path}")


def generate_reports(output_dir: str, report_dir: Optional[str] = None):
    target_dir = report_dir or output_dir
    os.makedirs(target_dir, exist_ok=True)

    print(f"\n{'=' * 60}")
    print("Generating sensitivity reports...")
    print(f"{'=' * 60}")

    for fname in sorted(os.listdir(output_dir)):
        if not fname.startswith("sensitivity_") or not fname.endswith(".json"):
            continue
        if fname.startswith("temp_"):
            continue

        json_path = os.path.join(output_dir, fname)
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        metrics = _compute_metrics(data)
        if metrics is None:
            print(f"  [SKIP] {fname}: no results")
            continue

        res_type = data["resource_type"]
        out_path = os.path.join(target_dir, f"report_{res_type}.png")
        _plot_report(data, metrics, out_path)

    print(f"[OK] Reports saved to {target_dir}")


def main():
    parser = argparse.ArgumentParser(
        description="多资源敏感性分析（资源间串行，资源内并行）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog="""
Examples:
  python sensitivity_batch.py --input base.json --workers 4 --vectorized

  python sensitivity_batch.py --input base.json \\
      --ranges patrol:0:50:5 camera:0:400:10 drone:0:20:1

  python sensitivity_batch.py --input base.json \\
      --ranges camera:0:400:50 --two-step --workers 4

  python sensitivity_batch.py --input base.json --no-report

Range format:  resource:min:max:step
  e.g.  camera:0:400:10  means camera count from 0 to 400, step 10
        """
    )
    parser.add_argument("--input", "-i", required=True, help="基础输入 JSON 路径")
    parser.add_argument("--ranges", nargs="+", default=None,
                        help="资源范围定义，格式 resource:min:max:step。"
                             "未指定的资源使用默认范围。"
                             "例: patrol:0:50:5 camera:0:400:10")
    parser.add_argument("--output", "-o", default=None,
                        help="敏感性分析中间结果目录（默认为 --report-dir 下的 sensitivity_results/）")
    parser.add_argument("--report-dir", default="./figures/single_sensitivity",
                        help="顶层输出目录，所有文件统一存放于此（默认 ./figures/single_sensitivity）")
    parser.add_argument("--workers", "-w", type=int, default=os.cpu_count(),
                        help="资源内并行工作进程数（默认系统核数）")
    parser.add_argument("--vectorized", action="store_true", default=False,
                        help="使用向量化模式（大规模地图推荐）")
    parser.add_argument("--two-step", action="store_true", default=False,
                        help="启用两步法：粗扫全范围后自动定位饱和区细扫")
    parser.add_argument("--fine-step-ratio", type=int, default=5,
                        help="两步法细扫步长 = 粗步长 / 此值（默认5）")
    parser.add_argument("--no-report", action="store_true", default=False,
                        help="跳过报告生成")
    parser.add_argument("--warm-start", action="store_true", default=False,
                        help="启用热启动：按资源值递增顺序串行执行，低资源点结果作为高资源点初始解")
    parser.add_argument("--warm-start-groups", type=int, default=None,
                        help="分组混合模式的并行组数（需配合 --warm-start 使用）。"
                             "默认1（纯串行），设为>1时启用分组并行，推荐设为workers数")
    parser.add_argument("--no-cache", action="store_true", default=False,
                        help="禁用缓存（默认启用缓存避免重复计算）")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: input file not found: {args.input}")
        sys.exit(1)

    report_dir = os.path.abspath(args.report_dir)
    sensitivity_output = args.output if args.output else os.path.join(report_dir, "sensitivity_results")

    ranges = parse_ranges(args.ranges)

    print("=" * 60)
    print("Multi-Resource Sensitivity Analysis")
    print("=" * 60)
    print(f"Input:            {args.input}")
    print(f"Report dir:       {report_dir}")
    print(f"Sensitivity data: {sensitivity_output}")
    print(f"Workers/resource: {args.workers}")
    print(f"Vectorized:       {args.vectorized}")
    print(f"Two-step:         {args.two_step}")
    if args.two_step:
        print(f"Fine step ratio:  {args.fine_step_ratio}")
    if args.warm_start:
        groups_str = str(args.warm_start_groups) if args.warm_start_groups else "1 (serial)"
        print(f"Warm-start:       enabled (groups={groups_str})")
    else:
        print(f"Warm-start:       disabled")
    print(f"Cache:            {'disabled' if args.no_cache else 'enabled'}")
    print(f"\nResources to analyze (serial between resources, parallel within):")
    for res, (lo, hi, step) in ranges.items():
        n_points = len(range(lo, hi + 1, step))
        print(f"  {res:<10} range=[{lo}, {hi}]  step={step}  ({n_points} points)")
    print("=" * 60)

    os.makedirs(report_dir, exist_ok=True)
    os.makedirs(sensitivity_output, exist_ok=True)

    print(f"\n[CLEAN] 清理缓存和临时文件...")
    cache_dir = os.path.join(sensitivity_output, '.cache')
    if os.path.exists(cache_dir):
        shutil.rmtree(cache_dir)
        print(f"  删除缓存目录: {cache_dir}")
    for pattern in ['temp_input_*.json', 'temp_output_*.json']:
        for f in glob_module.glob(os.path.join(sensitivity_output, pattern)):
            os.remove(f)
            print(f"  删除临时文件: {f}")

    input_abs = os.path.abspath(args.input)
    results = []
    start_time = time.time()

    for res, rng in ranges.items():
        result = run_single_resource(
            input_abs, res, rng, sensitivity_output,
            args.vectorized, args.workers,
            args.two_step, args.fine_step_ratio,
            warm_start=args.warm_start, warm_start_groups=args.warm_start_groups,
            no_cache=args.no_cache,
        )
        results.append(result)

    elapsed = time.time() - start_time

    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]

    print(f"\n{'=' * 60}")
    print("Summary")
    print(f"{'=' * 60}")
    print(f"Total:     {len(results)} resources")
    print(f"Success:   {len(successful)}")
    print(f"Failed:    {len(failed)}")
    print(f"Elapsed:   {elapsed:.1f}s")
    if failed:
        print("\nFailed resources:")
        for r in failed:
            print(f"  {r['resource']}: {r.get('error', 'unknown')[:100]}")

    config_path = os.path.join(report_dir, "batch_config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump({
            "input": input_abs,
            "ranges": {k: list(v) for k, v in ranges.items()},
            "workers": args.workers,
            "vectorized": args.vectorized,
            "two_step": args.two_step,
            "fine_step_ratio": args.fine_step_ratio,
            "warm_start": args.warm_start,
            "warm_start_groups": args.warm_start_groups,
            "cache_enabled": not args.no_cache,
            "results": results,
            "elapsed_seconds": elapsed,
        }, f, indent=2, ensure_ascii=False)

    if not args.no_report and successful:
        generate_reports(sensitivity_output, report_dir)

    print(f"\n[OK] Batch analysis complete. Results in: {report_dir}")


if __name__ == "__main__":
    main()
