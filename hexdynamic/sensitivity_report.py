"""
sensitivity_report.py — 敏感性分析报告生成器

读取 sensitivity_analysis.py 生成的 JSON 数据，生成优化后的可视化报告。

用法:
    python sensitivity_report.py sensitivity_results/sensitivity_camera.json
    python sensitivity_report.py sensitivity_results/ --all
    python sensitivity_report.py sensitivity_results/sensitivity_camera.json --out_dir ./reports
"""

import argparse
import json
import os
import glob

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------

def load_sensitivity(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_metrics(data: dict):
    results      = data["results"]
    res_values   = [r["resource_value"] for r in results]
    benefits     = [r["total_protection_benefit"] for r in results]
    fitnesses    = [r["best_fitness"] for r in results]

    # 边际收益（每增加一单位资源带来的收益增量）
    marginal = [0.0]
    for i in range(1, len(benefits)):
        dv = res_values[i] - res_values[i - 1]
        marginal.append((benefits[i] - benefits[i - 1]) / dv if dv else 0.0)

    # 饱和点：边际收益首次低于最大边际收益的 5%
    max_mb = max(marginal[1:]) if len(marginal) > 1 else 0
    saturation_idx = next(
        (i for i in range(1, len(marginal)) if marginal[i] < max_mb * 0.05),
        len(marginal) - 1
    )
    saturation_value = res_values[saturation_idx]

    # 收益增量百分比（相对于 0 资源时）
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


# ---------------------------------------------------------------------------
# 绘图
# ---------------------------------------------------------------------------

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


def _xlabel(res_type: str) -> str:
    return RESOURCE_LABEL.get(res_type.lower(), f"{res_type.capitalize()} Count")


def plot_report(data: dict, metrics: dict, out_path: str):
    res_type = data["resource_type"]
    m = metrics
    rv    = m["res_values"]
    sat   = m["saturation_value"]
    sat_i = m["saturation_idx"]

    # 计算表格行数，决定表格区域高度
    n = len(rv)
    step = max(1, n // 20)
    indices = list(range(0, n, step))
    if indices[-1] != n - 1:
        indices.append(n - 1)
    # 确保饱和点行一定出现在表格中
    if sat_i not in indices:
        indices.append(sat_i)
        indices.sort()
    n_rows = len(indices)

    # 图表区固定高度，表格区按行数动态扩展（每行约 0.28 英寸）
    chart_h  = 8.0
    table_h  = max(2.5, n_rows * 0.28 + 0.8)   # header + rows + title
    total_h  = chart_h + table_h + 0.6          # 0.6 for suptitle

    fig = plt.figure(figsize=(16, total_h))
    fig.suptitle(
        f"Sensitivity Analysis Report: {res_type.upper()}",
        fontsize=15, fontweight="bold", y=1.0 - 0.3 / total_h
    )

    # 用 subplot2grid 把图表区和表格区分开，比例由高度决定
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

    # 图表区再细分为 2×2
    gs_charts = gridspec.GridSpecFromSubplotSpec(
        2, 2, subplot_spec=gs[0], hspace=0.45, wspace=0.35
    )

    # ---- 1. Total Protection Benefit ----
    ax1 = fig.add_subplot(gs_charts[0, 0])
    ax1.plot(rv, m["benefits"], "o-", lw=2, ms=5, color=COLORS["benefit"])
    ax1.axvline(sat, color=COLORS["sat_line"], ls="--", lw=1.2, label=f"Saturation @ {sat}")
    ax1.set_xlabel(_xlabel(res_type), fontsize=10)
    ax1.set_ylabel("Total Protection Benefit", fontsize=10)
    ax1.set_title("Protection Benefit", fontsize=11, fontweight="bold")
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)

    # ---- 2. Best Fitness ----
    ax2 = fig.add_subplot(gs_charts[0, 1])
    ax2.plot(rv, m["fitnesses"], "s-", lw=2, ms=5, color=COLORS["fitness"])
    ax2.axvline(sat, color=COLORS["sat_line"], ls="--", lw=1.2, label=f"Saturation @ {sat}")
    ax2.set_xlabel(_xlabel(res_type), fontsize=10)
    ax2.set_ylabel("Best Fitness", fontsize=10)
    ax2.set_title("Best Fitness", fontsize=11, fontweight="bold")
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3)

    # ---- 3. Marginal Benefit ----
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

    # ---- 4. Cumulative Gain % ----
    ax4 = fig.add_subplot(gs_charts[1, 1])
    ax4.plot(rv, m["gain_pct"], "D-", lw=2, ms=5, color=COLORS["gain"])
    ax4.axvline(sat, color=COLORS["sat_line"], ls="--", lw=1.2, label=f"Saturation @ {sat}")
    ax4.set_xlabel(_xlabel(res_type), fontsize=10)
    ax4.set_ylabel("Benefit Gain vs Baseline (%)", fontsize=10)
    ax4.set_title("Cumulative Gain over Baseline", fontsize=11, fontweight="bold")
    ax4.legend(fontsize=8)
    ax4.grid(True, alpha=0.3)

    # ---- 5. Data Table ----
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
        loc="upper center",          # 顶部对齐，不居中漂移
        colWidths=[0.14, 0.18, 0.16, 0.18, 0.20],
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.scale(1, 1.4)

    # 表头样式
    for j in range(len(col_labels)):
        cell = tbl[(0, j)]
        cell.set_facecolor("#2c7bb6")
        cell.set_text_props(color="white", fontweight="bold")

    # 饱和点行高亮
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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def process_file(json_path: str, out_dir: str):
    data    = load_sensitivity(json_path)
    metrics = compute_metrics(data)
    res_type = data["resource_type"]

    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"report_{res_type}.png")
    plot_report(data, metrics, out_path)


def main():
    p = argparse.ArgumentParser(
        description="生成敏感性分析报告",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("input", help="sensitivity JSON 文件路径，或包含多个 JSON 的目录（配合 --all）")
    p.add_argument("--all", action="store_true", help="处理目录下所有 sensitivity_*.json 文件")
    p.add_argument("--out_dir", "-d", default=None,
                   help="图片输出目录（默认与输入文件同目录）")
    args = p.parse_args()

    if args.all:
        pattern = os.path.join(args.input, "sensitivity_*.json")
        files = [f for f in glob.glob(pattern)
                 if not os.path.basename(f).startswith("temp_")]
        if not files:
            print(f"未找到匹配文件: {pattern}")
            return
        for f in sorted(files):
            out_dir = args.out_dir or os.path.dirname(f)
            print(f"Processing: {f}")
            process_file(f, out_dir)
    else:
        out_dir = args.out_dir or os.path.dirname(os.path.abspath(args.input))
        process_file(args.input, out_dir)


if __name__ == "__main__":
    main()
