"""
time_risk_analyzer.py
时序风险对比分析脚本 - 分析 Day/Night × DRY/RAINY 四种时间组合的风险热力图

输入：单个 input JSON 文件（基础地图和物种配置）
输出：
  - 1 个地形图
  - 1 个物种密度图
  - 8 个单场景热力图（归一化 + 原始风险）
  - 1 个四象限原始风险对比图
  - 1 个分析摘要文件

用法：
    python time_risk_analyzer.py input.json
    python time_risk_analyzer.py input.json -o ./time_risk_analysis
    python time_risk_analyzer.py input.json --dpi 200 --grid_dpi 100
"""

import argparse
import copy
import json
import math
import os
import sys
from typing import Dict, List, Tuple, Optional

import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["figure.max_open_warning"] = 0
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from matplotlib.patches import Polygon
from matplotlib.colors import Normalize, LinearSegmentedColormap
from matplotlib import cm

import matplotlib.font_manager as fm

TERRAIN_COLORS = {
    "SparseGrass": "#a8d5a2",
    "DenseGrass":  "#2d6a2d",
    "WaterHole":   "#5b9bd5",
    "SaltMarsh":   "#c8b97a",
    "Road":        "#888888",
}

SPECIES_STYLE = {
    "rhino":    {"marker": "^", "color": "#8B4513", "size_scale": 120, "fill_color": "#8B4513"},
    "elephant": {"marker": "s", "color": "#708090", "size_scale": 120, "fill_color": "#708090"},
    "bird":     {"marker": "o", "color": "#FF6347",  "size_scale": 80,  "fill_color": "#FF6347"},
}

# 风险指数统一色阶：0 -> 淡黄，0.5 -> 橙，1 -> 深红（YlOrRd）
RISK_CMAP = matplotlib.colormaps.get_cmap("YlOrRd")

# 字体缩放基准：grid_dpi=80 时 fs=1.0，地图放大/缩小时字号等比缩放。
# 注意必须基于 grid_dpi（地图像素密度），而非 save_dpi（后者不改变字号相对比例）。
FONT_BASE_GRID_DPI = 80

def font_scale(grid_dpi: int) -> float:
    """根据 grid_dpi 计算字体缩放因子，并限制到合理区间避免过小/过大。"""
    if not grid_dpi or grid_dpi <= 0:
        return 1.0
    fs = grid_dpi / FONT_BASE_GRID_DPI
    return max(0.6, min(fs, 2.5))

SCENARIOS = [
    {"name": "day_dry",    "hour": 12, "season": "DRY",   "label": "Day + DRY",   "period": "DAY"},
    {"name": "day_rainy", "hour": 12, "season": "RAINY", "label": "Day + RAINY",  "period": "DAY"},
    {"name": "night_dry", "hour": 22, "season": "DRY",   "label": "Night + DRY",  "period": "NIGHT"},
    {"name": "night_rainy","hour": 22, "season": "RAINY", "label": "Night + RAINY","period": "NIGHT"},
]

def hex_corners(cx, cy, size):
    pts = []
    for i in range(6):
        a = math.pi / 3 * i + math.pi / 6
        pts.append((cx + size * math.cos(a), cy + size * math.sin(a)))
    return pts


def grid_center(q, r, size):
    col = q + (r // 2)
    x = size * math.sqrt(3) * (col + 0.5 * (r & 1))
    y = size * 1.5 * r
    return x, y


def draw_hex(ax, cx, cy, size, facecolor, edgecolor="black", lw=0.4, alpha=1.0, zorder=1):
    poly = Polygon(hex_corners(cx, cy, size), closed=True,
                   facecolor=facecolor, edgecolor=edgecolor,
                   linewidth=lw, alpha=alpha, zorder=zorder)
    ax.add_patch(poly)


def compute_scenario_risk(base_data: dict, hour: int, season: str) -> Tuple[Dict[int, float], Dict[int, float], Dict[int, float]]:
    """
    Compute risk for a specific scenario (hour, season).

    Returns:
        Tuple of (risk_normalized_map, temporal_factor_map, raw_risk_map)
    """
    data = copy.deepcopy(base_data)
    data['time'] = {
        'hour_of_day': hour,
        'season': season
    }
    data['use_temporal_factors'] = True

    from protection_pipeline import compute_risk_with_riskindex, smooth_risk_map_gaussian
    risk_map, temporal_factor_map, raw_risk_map = compute_risk_with_riskindex(data)

    # 与 protection_pipeline.run_pipeline 保持一致：可选高斯核空间平滑
    risk_cfg = data.get('risk_config', {})
    smoothing_cfg = risk_cfg.get('smoothing')
    if smoothing_cfg and smoothing_cfg.get('enabled', False):
        sigma = float(smoothing_cfg.get('sigma', 1.5))
        iterations = int(smoothing_cfg.get('iterations', 1))
        smooth_raw = bool(smoothing_cfg.get('smooth_raw', True))
        print(f"  [SMOOTH] sigma={sigma}, iterations={iterations}, smooth_raw={smooth_raw}")
        risk_map = smooth_risk_map_gaussian(risk_map, data['grids'],
                                             sigma=sigma, iterations=iterations)
        if smooth_raw:
            raw_risk_map = smooth_risk_map_gaussian(raw_risk_map, data['grids'],
                                                    sigma=sigma, iterations=iterations)
        # 平滑后重新归一化 risk_map 到 [0, 1]
        if risk_map:
            rmin, rmax = min(risk_map.values()), max(risk_map.values())
            if rmax > rmin:
                risk_map = {gid: (v - rmin) / (rmax - rmin) for gid, v in risk_map.items()}

    return risk_map, temporal_factor_map, raw_risk_map


def load_base_input(input_path: str) -> dict:
    """Load and validate base input JSON."""
    if not os.path.exists(input_path):
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON format in {input_path}: {e}", file=sys.stderr)
        sys.exit(1)

    if 'grids' not in data:
        print(f"Error: Input JSON must contain 'grids' field", file=sys.stderr)
        sys.exit(1)

    if len(data['grids']) == 0:
        print(f"Error: No grid data in input", file=sys.stderr)
        sys.exit(1)

    return data


def auto_grid_dpi(grids, max_grid_dpi=80):
    """Calculate appropriate grid_dpi based on map size."""
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


def plot_single_risk_heatmap(
    grids: List[dict],
    risk_map: Dict[int, float],
    hex_size: float,
    title: str,
    cmap_norm: Normalize,
    save_path: str,
    save_dpi: int = 150,
    grid_dpi: int = 80,
    show_grid_ids: bool = False
):
    """Plot a single risk heatmap."""
    cmap = RISK_CMAP
    fs = font_scale(grid_dpi)

    fig_w, fig_h = 14, 9
    ax_map = None
    ax_cbar = None
    ax_leg = None

    if grids:
        xs, ys = [], []
        for g in grids:
            cx, cy = grid_center(g["q"], g["r"], hex_size)
            xs.append(cx)
            ys.append(cy)

        margin = hex_size * 2
        data_width = max(xs) - min(xs) + hex_size * 2 + margin * 2
        data_height = max(ys) - min(ys) + hex_size * 2 + margin * 2
        hex_pixel_span = hex_size * math.sqrt(3)
        if hex_pixel_span == 0:
            hex_pixel_span = 1.0
        scale = grid_dpi / hex_pixel_span
        map_pixel_w = data_width * scale
        map_pixel_h = data_height * scale
        legend_pixel_w = grid_dpi * 4.5
        cbar_pixel_w = grid_dpi * 0.6
        total_pixel_w = map_pixel_w + cbar_pixel_w + legend_pixel_w
        total_pixel_h = max(map_pixel_h, grid_dpi * 6)
        fig_w = total_pixel_w / save_dpi
        fig_h = total_pixel_h / save_dpi

        fig = plt.figure(figsize=(fig_w, fig_h))

        left_margin = 0.01
        right_margin = 0.01
        top_margin = 0.06
        bottom_margin = 0.06

        usable_w = 1.0 - left_margin - right_margin
        usable_h = 1.0 - top_margin - bottom_margin

        heatmap_width_frac = map_pixel_w / total_pixel_w
        cbar_width_frac = cbar_pixel_w / total_pixel_w
        legend_width_frac = legend_pixel_w / total_pixel_w

        map_width = usable_w * heatmap_width_frac
        cbar_width = usable_w * cbar_width_frac
        legend_width = usable_w * legend_width_frac

        gap1 = 0.01
        gap2 = 0.01

        ax_map = fig.add_axes([
            left_margin,
            bottom_margin,
            map_width,
            usable_h
        ])

        cbar_left = left_margin + map_width + gap1
        cbar_height = usable_h * 0.5
        cbar_bottom = bottom_margin + usable_h * 0.25
        ax_cbar = fig.add_axes([
            cbar_left,
            cbar_bottom,
            cbar_width,
            cbar_height
        ])

        legend_left = cbar_left + cbar_width + gap2
        ax_leg = fig.add_axes([
            legend_left,
            bottom_margin,
            legend_width - gap2,
            usable_h
        ])
    else:
        fig = plt.figure(figsize=(14, 9))
        ax_map = fig.add_axes([0.02, 0.06, 0.68, 0.86])
        ax_cbar = fig.add_axes([0.72, 0.12, 0.025, 0.62])
        ax_leg = fig.add_axes([0.77, 0.06, 0.21, 0.86])

    ax_leg.axis("off")

    if grids:
        for g in grids:
            cx, cy = grid_center(g["q"], g["r"], hex_size)
            rid = g["grid_id"]
            risk_val = risk_map.get(rid, 0.0)
            draw_hex(ax_map, cx, cy, hex_size * 0.97, facecolor=cmap(cmap_norm(risk_val)))
            if show_grid_ids:
                ax_map.text(cx, cy, str(rid), ha="center", va="center", fontsize=5*fs, zorder=4)

        ax_map.set_aspect("equal")
        ax_map.axis("off")

        xs = [grid_center(g["q"], g["r"], hex_size)[0] for g in grids]
        ys = [grid_center(g["q"], g["r"], hex_size)[1] for g in grids]
        margin = hex_size * 1.5
        ax_map.set_xlim(min(xs) - margin, max(xs) + margin)
        ax_map.set_ylim(min(ys) - margin, max(ys) + margin)

    ax_map.set_title(title, fontsize=12*fs, fontweight="bold", pad=8)

    sm = cm.ScalarMappable(cmap=cmap, norm=cmap_norm)
    sm.set_array([])
    fig.colorbar(sm, cax=ax_cbar)
    ax_cbar.tick_params(labelsize=8*fs)

    risk_vals = list(risk_map.values())
    n = len(risk_vals)
    items = [
        ("Summary", None, True),
        ("Total Grids", str(n), False),
        ("Risk Min", f"{min(risk_vals):.4f}", False),
        ("Risk Max", f"{max(risk_vals):.4f}", False),
        ("Risk Mean", f"{sum(risk_vals)/n:.4f}", False),
    ]
    y = 0.97
    for label, value, bold in items:
        text = label if value is None else f"{label}: {value}"
        ax_leg.text(0.05, y, text, transform=ax_leg.transAxes,
                    fontsize=9*fs, va="top",
                    fontweight="bold" if bold else "normal",
                    fontfamily="monospace")
        y -= 0.09

    # 底部统计指标
    if risk_vals:
        stats_text = f"Max: {max(risk_vals):.4f}    Min: {min(risk_vals):.4f}    Mean: {np.mean(risk_vals):.4f}    Var: {np.var(risk_vals):.6f}"
        map_pos = ax_map.get_position()
        fig.text(map_pos.x0 + map_pos.width / 2, 0.015, stats_text,
                 ha='center', va='bottom', fontsize=9*fs,
                 fontfamily='monospace', fontweight='bold')

    fig.savefig(save_path, dpi=save_dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved: {save_path}")


def plot_4panel_comparison(
    scenarios_data: List[dict],
    grids: List[dict],
    hex_size: float,
    max_raw_risk: float,
    save_path: str,
    save_dpi: int = 150,
    grid_dpi: int = 80,
    diurnal_mode: str = "discrete"
):
    """Plot a 4-panel comparison of raw risks across all scenarios."""
    cmap = RISK_CMAP
    cmap_norm = Normalize(vmin=0, vmax=max_raw_risk if max_raw_risk > 0 else 1)
    fs = font_scale(grid_dpi)

    if grids:
        xs, ys = [], []
        for g in grids:
            cx, cy = grid_center(g["q"], g["r"], hex_size)
            xs.append(cx)
            ys.append(cy)

        margin = hex_size * 2
        data_width = max(xs) - min(xs) + hex_size * 2 + margin * 2
        data_height = max(ys) - min(ys) + hex_size * 2 + margin * 2
        hex_pixel_span = hex_size * math.sqrt(3)
        if hex_pixel_span == 0:
            hex_pixel_span = 1.0
        scale = grid_dpi / hex_pixel_span
        map_pixel_w = data_width * scale
        map_pixel_h = data_height * scale
        cbar_pixel_h = map_pixel_h * 0.6
        total_pixel_w = map_pixel_w * 2 + grid_dpi * 2
        total_pixel_h = max(map_pixel_h * 2 + cbar_pixel_h, grid_dpi * 8)
        fig_w = total_pixel_w / save_dpi
        fig_h = total_pixel_h / save_dpi
    else:
        fig_w, fig_h = 16, 14

    fig = plt.figure(figsize=(fig_w, fig_h))

    left_margin = 0.02
    right_margin = 0.02
    top_margin = 0.06
    bottom_margin = 0.06

    usable_w = 1.0 - left_margin - right_margin
    usable_h = 1.0 - top_margin - bottom_margin

    cbar_width = 0.02
    cbar_right = 1.0 - right_margin
    cbar_left = cbar_right - cbar_width

    gap_between_panels = 0.01
    panel_area_width = cbar_left - left_margin - gap_between_panels
    panel_w = (panel_area_width - gap_between_panels) / 2

    panel_area_height = usable_h
    panel_h = (panel_area_height - gap_between_panels) / 2

    positions = [
        (left_margin, bottom_margin + panel_h + gap_between_panels, panel_w, panel_h),
        (left_margin + panel_w + gap_between_panels, bottom_margin + panel_h + gap_between_panels, panel_w, panel_h),
        (left_margin, bottom_margin, panel_w, panel_h),
        (left_margin + panel_w + gap_between_panels, bottom_margin, panel_w, panel_h),
    ]

    for scenario, pos in zip(scenarios_data, positions):
        ax = fig.add_axes(list(pos))
        risk_map = scenario["raw_risk_map"]

        for g in grids:
            cx, cy = grid_center(g["q"], g["r"], hex_size)
            rid = g["grid_id"]
            risk_val = risk_map.get(rid, 0.0)
            draw_hex(ax, cx, cy, hex_size * 0.97, facecolor=cmap(cmap_norm(risk_val)))

        ax.set_aspect("equal")
        ax.axis("off")

        xs = [grid_center(g["q"], g["r"], hex_size)[0] for g in grids]
        ys = [grid_center(g["q"], g["r"], hex_size)[1] for g in grids]
        margin = hex_size * 1.5
        ax.set_xlim(min(xs) - margin, max(xs) + margin)
        ax.set_ylim(min(ys) - margin, max(ys) + margin)

        ax.set_title(scenario["label"], fontsize=12*fs, fontweight="bold", pad=4)

    stats_fontsize = 9*fs
    for scenario, pos in zip(scenarios_data, positions):
        panel_x, panel_y, panel_w, panel_h = pos
        stats_height = 0.05
        stats_ax = fig.add_axes([panel_x, panel_y - stats_height, panel_w, stats_height])
        stats_ax.axis("off")

        risk_vals = list(scenario["raw_risk_map"].values())
        temporal_vals = list(scenario["temporal_factor_map"].values())

        if diurnal_mode == "continuous":
            time_label = f"{scenario['hour']:02d}:00"
        else:
            time_label = scenario.get("period", "DAY" if scenario["hour"] == 12 else "NIGHT")

        stats_text = (
            f"{time_label}/{scenario['season']}  "
            f"R:[{min(risk_vals):.3f},{max(risk_vals):.3f}]  "
            f"Mean:{np.mean(risk_vals):.4f}  Std:{np.std(risk_vals):.4f}  "
            f"T:[{min(temporal_vals):.2f},{max(temporal_vals):.2f}]"
        )
        stats_ax.text(0.5, 0.5, stats_text, transform=stats_ax.transAxes,
                      fontsize=stats_fontsize, va='center', ha='center',
                      fontfamily="monospace",
                      bbox=dict(boxstyle="round,pad=0.3", facecolor="#f5f5f5",
                               edgecolor="#ccc", alpha=0.95))

    cbar_bottom = bottom_margin + panel_h * 0.2
    cbar_height = panel_h * 1.6
    cbar_ax = fig.add_axes([cbar_left, cbar_bottom, cbar_width, cbar_height])
    sm = cm.ScalarMappable(cmap=cmap, norm=cmap_norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, cax=cbar_ax)
    cbar.set_label("Raw Risk", fontsize=11*fs)
    cbar.ax.tick_params(labelsize=10*fs)

    fig.suptitle("Risk Comparison Across Time Scenarios\n(Raw Risk, Unified Color Scale)",
                 fontsize=12*fs, fontweight="bold", y=0.98)

    fig.savefig(save_path, dpi=save_dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved: {save_path}")


def generate_summary(scenarios_data: List[dict], grids: List[dict], save_path: str):
    """Generate analysis summary text file."""
    lines = []
    lines.append("=" * 70)
    lines.append("时序风险对比分析摘要 / Temporal Risk Comparison Summary")
    lines.append("=" * 70)
    lines.append(f"Total grids analyzed: {len(grids)}")
    lines.append("")

    for scenario in scenarios_data:
        norm_map = scenario["norm_risk_map"]
        raw_map = scenario["raw_risk_map"]
        temporal_map = scenario["temporal_factor_map"]

        norm_vals = list(norm_map.values())
        raw_vals = list(raw_map.values())
        temporal_vals = list(temporal_map.values())

        lines.append(f"{'─' * 70}")
        lines.append(f"Scenario: {scenario['label']}")
        lines.append(f"  Period: {scenario.get('period', 'DAY' if scenario['hour'] == 12 else 'NIGHT')}, Hour: {scenario['hour']:02d}:00, Season: {scenario['season']}")
        lines.append("")
        lines.append(f"  Normalized Risk:")
        lines.append(f"    Min:    {min(norm_vals):.6f}")
        lines.append(f"    Max:    {max(norm_vals):.6f}")
        lines.append(f"    Mean:   {sum(norm_vals)/len(norm_vals):.6f}")
        lines.append(f"    Std:    {np.std(norm_vals):.6f}")
        lines.append("")
        lines.append(f"  Raw Risk:")
        lines.append(f"    Min:    {min(raw_vals):.6f}")
        lines.append(f"    Max:    {max(raw_vals):.6f}")
        lines.append(f"    Mean:   {sum(raw_vals)/len(raw_vals):.6f}")
        lines.append(f"    Std:    {np.std(raw_vals):.6f}")
        lines.append("")
        lines.append(f"  Temporal Factor:")
        lines.append(f"    Min:    {min(temporal_vals):.6f}")
        lines.append(f"    Max:    {max(temporal_vals):.6f}")
        lines.append(f"    Mean:   {sum(temporal_vals)/len(temporal_vals):.6f}")

    lines.append("")
    lines.append(f"{'=' * 70}")
    lines.append("Cross-Scenario Comparison")
    lines.append(f"{'=' * 70}")
    max_raw = max(max(s["raw_risk_map"].values()) for s in scenarios_data)
    min_raw = min(min(s["raw_risk_map"].values()) for s in scenarios_data)
    max_norm = max(max(s["norm_risk_map"].values()) for s in scenarios_data)
    min_norm = min(min(s["norm_risk_map"].values()) for s in scenarios_data)

    lines.append(f"Raw Risk Range: [{min_raw:.6f}, {max_raw:.6f}]")
    lines.append(f"Normalized Risk Range: [{min_norm:.6f}, {max_norm:.6f}]")
    lines.append("")

    with open(save_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f"  saved: {save_path}")


def plot_terrain_map(grids, hex_size, save_path, grid_dpi=80, save_dpi=150):
    n_grids = len(grids)
    if n_grids == 0:
        return
    fs = font_scale(grid_dpi)

    xs = [grid_center(g["q"], g["r"], hex_size)[0] for g in grids]
    ys = [grid_center(g["q"], g["r"], hex_size)[1] for g in grids]
    margin = hex_size * 2
    data_width = max(xs) - min(xs) + hex_size * 2 + margin * 2
    data_height = max(ys) - min(ys) + hex_size * 2 + margin * 2
    hex_pixel_span = hex_size * math.sqrt(3)
    if hex_pixel_span == 0:
        hex_pixel_span = 1.0
    scale = grid_dpi / hex_pixel_span
    map_pixel_w = data_width * scale
    map_pixel_h = data_height * scale
    legend_pixel_w = grid_dpi * 4.5
    total_pixel_w = map_pixel_w + legend_pixel_w
    total_pixel_h = max(map_pixel_h, grid_dpi * 6)
    fig_w = total_pixel_w / save_dpi
    fig_h = total_pixel_h / save_dpi

    left_margin = 0.01
    right_margin = 0.01
    top_margin = 0.06
    bottom_margin = 0.06
    usable_w = 1.0 - left_margin - right_margin
    usable_h = 1.0 - top_margin - bottom_margin
    map_width_frac = map_pixel_w / total_pixel_w
    legend_width_frac = legend_pixel_w / total_pixel_w
    map_width = usable_w * map_width_frac
    legend_width = usable_w * legend_width_frac

    fig = plt.figure(figsize=(fig_w, fig_h))
    ax_map = fig.add_axes([left_margin, bottom_margin, map_width, usable_h])
    ax_leg = fig.add_axes([left_margin + map_width, bottom_margin, legend_width, usable_h])

    for g in grids:
        cx, cy = grid_center(g["q"], g["r"], hex_size)
        fc = TERRAIN_COLORS.get(g.get("terrain_type", ""), "#dddddd")
        draw_hex(ax_map, cx, cy, hex_size, facecolor=fc, alpha=0.85)

    ax_map.set_aspect("equal")
    ax_map.axis("off")
    ax_map.set_xlim(min(xs) - margin, max(xs) + margin)
    ax_map.set_ylim(min(ys) - margin, max(ys) + margin)
    ax_map.set_title("Terrain Map", fontsize=13*fs, fontweight="bold", pad=8)

    handles = [mpatches.Patch(facecolor=c, edgecolor="black", linewidth=0.5, label=t)
               for t, c in TERRAIN_COLORS.items()]
    ax_leg.legend(handles=handles, loc="center", fontsize=10*fs,
                  title="Terrain Types", title_fontsize=11*fs,
                  frameon=True, fancybox=True, edgecolor="gray")
    ax_leg.axis("off")
    fig.savefig(save_path, dpi=save_dpi)
    plt.close(fig)
    print(f"  saved: {save_path}")


def _species_stats_text(grids, all_species):
    total = len(grids)
    lines = []
    for sp in all_species:
        vals = [g["species_densities"][sp] for g in grids if g.get("species_densities", {}).get(sp, 0) > 0]
        if not vals:
            continue
        cnt = len(vals)
        pct = 100 * cnt / total
        lo, hi = min(vals), max(vals)
        avg = sum(vals) / cnt
        lines.append(f"{sp}: {cnt} grids ({pct:.1f}%), density [{lo:.2f}, {hi:.2f}], mean={avg:.2f}")
    overlap = sum(1 for g in grids
                  if sum(1 for sp in g.get("species_densities", {})
                         if g["species_densities"][sp] > 0) > 1)
    if overlap > 0:
        lines.append(f"Multi-species hotspot grids: {overlap}")
    return "\n".join(lines)


def _draw_hex_heatmap(ax, grids, hex_size, species, cmap, norm):
    from matplotlib.patches import Polygon
    from matplotlib.collections import PatchCollection
    patches = []
    colors = []
    for g in grids:
        cx, cy = grid_center(g["q"], g["r"], hex_size)
        corners = hex_corners(cx, cy, hex_size * 0.97)
        patches.append(Polygon(corners, closed=True))
        d = g.get("species_densities", {}).get(species, 0)
        colors.append(cmap(norm(d)))
    pc = PatchCollection(patches, facecolors=colors, edgecolors="black", linewidths=0.3)
    ax.add_collection(pc)
    ax.set_aspect("equal")
    ax.autoscale_view()
    ax.axis("off")


def _draw_composite(ax, grids, hex_size, all_species):
    from matplotlib.patches import Polygon
    from matplotlib.collections import PatchCollection
    import matplotlib.colors as mcolors

    terrain_patches = []
    terrain_colors = []
    species_patches = {sp: [] for sp in all_species}
    multi_species_grids = []

    for g in grids:
        cx, cy = grid_center(g["q"], g["r"], hex_size)
        corners = hex_corners(cx, cy, hex_size * 0.97)
        sd = g.get("species_densities", {})
        active = [(sp, sd[sp]) for sp in all_species if sd.get(sp, 0) > 0]

        if not active:
            terrain_patches.append(Polygon(corners, closed=True))
            terrain_colors.append(TERRAIN_COLORS.get(g.get("terrain_type", ""), "#dddddd"))
        elif len(active) == 1:
            sp, d = active[0]
            species_patches[sp].append((Polygon(corners, closed=True), d))
        else:
            multi_species_grids.append((cx, cy, active, corners))

    if terrain_patches:
        pc = PatchCollection(terrain_patches, facecolors=terrain_colors,
                             edgecolors="black", linewidths=0.3, alpha=0.5)
        ax.add_collection(pc)

    for sp in all_species:
        if not species_patches[sp]:
            continue
        patches, densities = zip(*species_patches[sp])
        fill_color = SPECIES_STYLE.get(sp, {}).get("fill_color", "#333")
        base_rgb = mcolors.to_rgb(fill_color)
        face_colors = [(*base_rgb, 0.3 + 0.6 * d) for d in densities]
        pc = PatchCollection(patches, facecolors=face_colors,
                             edgecolors="black", linewidths=0.3)
        ax.add_collection(pc)

    for cx, cy, active, corners in multi_species_grids:
        border_x = [c[0] for c in corners] + [corners[0][0]]
        border_y = [c[1] for c in corners] + [corners[0][1]]
        ax.plot(border_x, border_y, color="black", linewidth=0.3, zorder=4)
        total_d = sum(d for _, d in active)
        angle_start = 90
        r = hex_size * 0.85
        for sp, d in active:
            fill_color = SPECIES_STYLE.get(sp, {}).get("fill_color", "#333")
            sweep = 360 * d / total_d
            theta1 = math.radians(angle_start)
            theta2 = math.radians(angle_start + sweep)
            n_pts = max(3, int(sweep / 15) + 1)
            angles = [theta1 + (theta2 - theta1) * i / n_pts for i in range(n_pts + 1)]
            pts = [(cx, cy)] + [(cx + r * math.cos(a), cy + r * math.sin(a)) for a in angles]
            ax.fill(*zip(*pts), facecolor=fill_color, edgecolor="none", alpha=0.8, zorder=3)
            angle_start += sweep

    ax.set_aspect("equal")
    ax.autoscale_view()
    ax.axis("off")


def _compute_panel_figsize(grids, hex_size, grid_dpi, save_dpi):
    xs = [grid_center(g["q"], g["r"], hex_size)[0] for g in grids]
    ys = [grid_center(g["q"], g["r"], hex_size)[1] for g in grids]
    margin = hex_size * 2
    data_width = max(xs) - min(xs) + hex_size * 2 + margin * 2
    data_height = max(ys) - min(ys) + hex_size * 2 + margin * 2
    hex_pixel_span = hex_size * math.sqrt(3)
    if hex_pixel_span == 0:
        hex_pixel_span = 1.0
    scale = grid_dpi / hex_pixel_span
    map_pixel_w = data_width * scale
    map_pixel_h = data_height * scale
    cbar_pixel_w = grid_dpi * 0.6
    single_pixel_w = map_pixel_w + cbar_pixel_w
    single_pixel_h = max(map_pixel_h, grid_dpi * 4)
    single_fig_w = single_pixel_w / save_dpi
    single_fig_h = single_pixel_h / save_dpi
    return single_fig_w, single_fig_h


def plot_species_density_map(grids, hex_size, save_path, grid_dpi=80, save_dpi=150):
    n_grids = len(grids)
    if n_grids == 0:
        return
    fs = font_scale(grid_dpi)
    all_species = set()
    for g in grids:
        for sp, d in g.get("species_densities", {}).items():
            if d > 0:
                all_species.add(sp)
    all_species = sorted(all_species)
    if not all_species:
        return

    stats_text = _species_stats_text(grids, all_species)
    n_stats_lines = stats_text.count("\n") + 1
    stats_pixel_h = grid_dpi * (0.5 + n_stats_lines * 0.25)

    xs = [grid_center(g["q"], g["r"], hex_size)[0] for g in grids]
    ys = [grid_center(g["q"], g["r"], hex_size)[1] for g in grids]
    margin = hex_size * 2
    data_width = max(xs) - min(xs) + hex_size * 2 + margin * 2
    data_height = max(ys) - min(ys) + hex_size * 2 + margin * 2
    hex_pixel_span = hex_size * math.sqrt(3)
    if hex_pixel_span == 0:
        hex_pixel_span = 1.0
    scale = grid_dpi / hex_pixel_span
    map_pixel_w = data_width * scale
    map_pixel_h = data_height * scale
    legend_pixel_w = grid_dpi * 4.5
    total_pixel_w = map_pixel_w + legend_pixel_w
    map_plus_leg_h = max(map_pixel_h, grid_dpi * 6)
    total_pixel_h = map_plus_leg_h + stats_pixel_h
    fig_w = total_pixel_w / save_dpi
    fig_h = total_pixel_h / save_dpi

    left_margin = 0.01
    right_margin = 0.01
    top_margin = 0.06
    bottom_margin = 0.02
    usable_w = 1.0 - left_margin - right_margin
    usable_h = 1.0 - top_margin - bottom_margin
    map_frac_h = map_plus_leg_h / total_pixel_h
    stats_frac_h = stats_pixel_h / total_pixel_h
    map_width_frac = map_pixel_w / total_pixel_w
    legend_width_frac = legend_pixel_w / total_pixel_w
    map_width = usable_w * map_width_frac
    legend_width = usable_w * legend_width_frac
    map_h = usable_h * map_frac_h
    stats_h = usable_h * stats_frac_h

    fig = plt.figure(figsize=(fig_w, fig_h))
    ax_map = fig.add_axes([left_margin, bottom_margin + stats_h, map_width, map_h])
    ax_leg = fig.add_axes([left_margin + map_width, bottom_margin + stats_h, legend_width, map_h])
    ax_stats = fig.add_axes([left_margin, bottom_margin, usable_w, stats_h])

    for g in grids:
        cx, cy = grid_center(g["q"], g["r"], hex_size)
        fc = TERRAIN_COLORS.get(g.get("terrain_type", ""), "#dddddd")
        draw_hex(ax_map, cx, cy, hex_size, facecolor=fc, alpha=0.5)

    for g in grids:
        sd = g.get("species_densities", {})
        active = [sp for sp in all_species if sd.get(sp, 0) > 0]
        if not active:
            continue
        cx, cy = grid_center(g["q"], g["r"], hex_size)
        n = len(active)
        for i, sp in enumerate(active):
            style = SPECIES_STYLE.get(sp, {"marker": "P", "color": "#333", "size_scale": 80})
            ox = (i - (n - 1) / 2) * hex_size * 0.35
            size = max(10, style["size_scale"] * sd[sp])
            ax_map.scatter(cx + ox, cy, marker=style["marker"], s=size,
                           color=style["color"], edgecolors="black",
                           linewidths=0.4, alpha=0.85, zorder=4)

    ax_map.set_aspect("equal")
    ax_map.axis("off")
    ax_map.set_xlim(min(xs) - margin, max(xs) + margin)
    ax_map.set_ylim(min(ys) - margin, max(ys) + margin)
    ax_map.set_title("Species Density Map", fontsize=13*fs, fontweight="bold", pad=8)

    terrain_handles = [mpatches.Patch(facecolor=c, edgecolor="black", linewidth=0.5, alpha=0.5, label=t)
                       for t, c in TERRAIN_COLORS.items()]
    species_handles = [
        plt.Line2D([0], [0], marker=SPECIES_STYLE.get(sp, {}).get("marker", "o"),
                   color="w", markerfacecolor=SPECIES_STYLE.get(sp, {}).get("color", "#333"),
                   markeredgecolor="black", markersize=9, label=f"{sp} (size ~ density)")
        for sp in all_species
    ]
    all_handles = terrain_handles + species_handles
    ax_leg.legend(handles=all_handles, loc="center", fontsize=10*fs,
                  title="Legend", title_fontsize=11*fs,
                  frameon=True, fancybox=True, edgecolor="gray")
    ax_leg.axis("off")

    ax_stats.axis("off")
    ax_stats.text(0.01, 0.9, stats_text, fontsize=9*fs, fontfamily="monospace",
                  verticalalignment="top", transform=ax_stats.transAxes,
                  bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor="gray", alpha=0.9))

    fig.savefig(save_path, dpi=save_dpi)
    plt.close(fig)
    print(f"  saved: {save_path}")


def plot_species_density_panels(grids, hex_size, save_path, grid_dpi=20, save_dpi=150):
    import matplotlib.colors as mcolors
    from matplotlib.cm import ScalarMappable

    n_grids = len(grids)
    if n_grids == 0:
        return
    fs = font_scale(grid_dpi)
    all_species = set()
    for g in grids:
        for sp, d in g.get("species_densities", {}).items():
            if d > 0:
                all_species.add(sp)
    all_species = sorted(all_species)
    if not all_species:
        return

    stats_text = _species_stats_text(grids, all_species)
    n_species = len(all_species)
    n_panels = n_species + 1

    if n_panels <= 2:
        nrows, ncols = 1, n_panels
    elif n_panels <= 4:
        nrows, ncols = 2, 2
    else:
        nrows = (n_panels + 1) // 2
        ncols = 2

    single_w, single_h = _compute_panel_figsize(grids, hex_size, grid_dpi, save_dpi)
    gap = 0.3
    fig_w = single_w * ncols + gap * (ncols - 1)
    fig_h = single_h * nrows + gap * (nrows - 1) + 0.8

    panel_w = single_w / fig_w
    panel_h = single_h / fig_h
    gap_frac_w = gap / fig_w
    gap_frac_h = gap / fig_h
    title_h = 0.04

    fig = plt.figure(figsize=(fig_w, fig_h))

    for idx, sp in enumerate(all_species):
        row = idx // ncols
        col = idx % ncols
        left = col * (panel_w + gap_frac_w)
        bottom = (nrows - 1 - row) * (panel_h + gap_frac_h) + 0.06

        ax = fig.add_axes([left, bottom, panel_w * 0.88, panel_h - title_h])
        fill_color = SPECIES_STYLE.get(sp, {}).get("fill_color", "#333333")
        cmap = mcolors.LinearSegmentedColormap.from_list(f"{sp}_cmap", ["#f0f0f0", fill_color])
        norm = plt.Normalize(0, 1)
        _draw_hex_heatmap(ax, grids, hex_size, sp, cmap, norm)

        cbar_left = left + panel_w * 0.88 + 0.005
        cbar_bottom = bottom + panel_h * 0.15
        cbar_h = panel_h * 0.7 - title_h
        ax_cbar = fig.add_axes([cbar_left, cbar_bottom, panel_w * 0.04, cbar_h])
        sm = ScalarMappable(cmap=cmap, norm=norm)
        sm.set_array([])
        cbar = fig.colorbar(sm, cax=ax_cbar)
        cbar.set_label("Density", fontsize=8*fs)
        cbar.ax.tick_params(labelsize=7*fs)

        fig.text(left + panel_w * 0.44, bottom + panel_h - title_h * 0.3,
                 f"{sp.capitalize()} Density", fontsize=11*fs, fontweight="bold",
                 ha="center", va="bottom")

    comp_idx = n_species
    comp_row = comp_idx // ncols
    comp_col = comp_idx % ncols
    comp_left = comp_col * (panel_w + gap_frac_w)
    comp_bottom = (nrows - 1 - comp_row) * (panel_h + gap_frac_h) + 0.06

    ax_comp = fig.add_axes([comp_left, comp_bottom, panel_w, panel_h - title_h])
    _draw_composite(ax_comp, grids, hex_size, all_species)
    fig.text(comp_left + panel_w * 0.5, comp_bottom + panel_h - title_h * 0.3,
             "Composite Overview", fontsize=11*fs, fontweight="bold", ha="center", va="bottom")

    legend_items = []
    for sp in all_species:
        fill_color = SPECIES_STYLE.get(sp, {}).get("fill_color", "#333")
        legend_items.append(mpatches.Patch(facecolor=fill_color, edgecolor="black",
                                           linewidth=0.5, alpha=0.7, label=sp))
    terrain_items = [mpatches.Patch(facecolor=c, edgecolor="black", linewidth=0.5, alpha=0.5, label=t)
                     for t, c in TERRAIN_COLORS.items()]
    ax_comp.legend(handles=terrain_items + legend_items, loc="upper right", fontsize=7*fs, framealpha=0.8)

    fig.text(0.02, 0.01, stats_text, fontsize=9*fs, fontfamily="monospace",
             verticalalignment="bottom",
             bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor="gray", alpha=0.9))

    fig.suptitle("Species Density Panels", fontsize=14*fs, fontweight="bold", y=0.99)
    fig.savefig(save_path, dpi=save_dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved: {save_path}")


def plot_re_scatter_4panel(
    scenarios_data: List[dict],
    grids: List[dict],
    protection_ratio: Dict[int, float],
    save_path: str,
    save_dpi: int = 150,
):
    """Plot 2x2 R-E scatter (Inherent Risk vs Protection Strength) for 4 scenarios.

    Ri = normalized inherent (pre-deployment) risk per scenario
    Ei = Ri * protection_ratio  (protection_benefit / risk, derived from best deployment)
    Diagonal Ei=Ri is ideal; deficit area (Ei < Ri) is shaded pink in panel (d).
    Points colored by Ri using YlOrRd; dark blue dashed line is empirical trend.
    """
    panel_titles = [
        "(a) Day & Dry: Optimal Matching",
        "(b) Day & Rainy: Visibility Attenuation",
        "(c) Night & Dry: Choke-point Defense",
        "(d) Night & Rainy: Protection Deficit",
    ]

    fig, axes = plt.subplots(2, 2, figsize=(14, 12))
    axes = axes.flatten()

    cmap = RISK_CMAP
    scatter_cmap = matplotlib.colormaps.get_cmap("YlOrRd")

    for idx, (scenario, ax, title) in enumerate(zip(scenarios_data, axes, panel_titles)):
        risk_map = scenario["norm_risk_map"]

        ris = []
        eis = []
        for g in grids:
            gid = g["grid_id"]
            ri = risk_map.get(gid, 0.0)
            ratio = protection_ratio.get(gid, 0.0)
            ei = ri * ratio
            if ei > 1.0:
                ei = 1.0
            ris.append(ri)
            eis.append(ei)

        ris = np.array(ris)
        eis = np.array(eis)

        # Scatter points colored by Ri
        sc = ax.scatter(ris, eis, c=ris, cmap=scatter_cmap, vmin=0, vmax=1,
                        s=12, alpha=0.5, edgecolors='none', zorder=2)

        # Ideal baseline Ei=Ri
        ax.plot([0, 1], [0, 1], color="#E04030", linewidth=1.5, linestyle="-",
                label=r"Ideal Baseline ($E_i = R_i$)", zorder=3)

        # Empirical trend: Gaussian-weighted moving average (LOESS-style)
        sorted_idx = np.argsort(ris)
        r_sorted = ris[sorted_idx]
        e_sorted = eis[sorted_idx]
        n_pts = len(r_sorted)
        trend_x = None
        trend_y = None
        if n_pts >= 20:
            x_eval = np.linspace(0.0, 1.0, 120)
            bandwidth = 0.10
            y_smooth = np.zeros_like(x_eval)
            for k, xv in enumerate(x_eval):
                w = np.exp(-0.5 * ((r_sorted - xv) / bandwidth) ** 2)
                w_sum = np.sum(w)
                y_smooth[k] = np.sum(w * e_sorted) / w_sum if w_sum > 0 else 0.0
            y_smooth[0] = 0.0
            for k in range(1, len(y_smooth)):
                y_smooth[k] = max(y_smooth[k], y_smooth[k - 1])
            y_smooth = np.clip(y_smooth, 0, 1)
            trend_x = x_eval
            trend_y = y_smooth
            ax.plot(trend_x, trend_y, color="#2C3E50", linewidth=2.8,
                    linestyle="--", label="Empirical Trend", zorder=4)

        # Protection deficit area (panel d): where risk is high AND protection lags significantly
        if idx == 3 and trend_x is not None:
            gap = trend_x - trend_y
            deficit_mask = (trend_x >= 0.5) & (gap > 0.20)
            if np.any(deficit_mask):
                fd_x = trend_x[deficit_mask]
                fd_y = trend_y[deficit_mask]
                ax.fill_between(fd_x, fd_y, fd_x, color="#FFB6C1", alpha=0.30,
                                label="Protection Deficit Area", zorder=1)

        ax.set_xlim(0, 1.02)
        ax.set_ylim(0, 1.02)
        ax.set_xlabel(r"Inherent Risk Index ($R_i$)", fontsize=11)
        ax.set_ylabel(r"Integrated Protection Strength ($E_i$)", fontsize=11)
        ax.set_title(title, fontsize=13, fontweight="bold", pad=8)
        ax.legend(loc="upper left", fontsize=9, framealpha=0.9)
        ax.grid(True, alpha=0.15)
        ax.set_aspect("equal", adjustable="box")

    # Shared colorbar on the right
    fig.subplots_adjust(right=0.90, wspace=0.25, hspace=0.28)
    cbar_ax = fig.add_axes([0.92, 0.15, 0.02, 0.7])
    cbar = fig.colorbar(sc, cax=cbar_ax)
    cbar.set_label(r"Inherent Risk Intensity ($R_i$)", fontsize=11, rotation=270, labelpad=18)

    fig.savefig(save_path, dpi=save_dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved: {save_path}")


def parse_args():
    p = argparse.ArgumentParser(
        description="时序风险对比分析 - 分析 Day/Night × DRY/RAINY 四种时间组合",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog="""
示例:
  python time_risk_analyzer.py input.json
  python time_risk_analyzer.py input.json -o ./time_risk_analysis
  python time_risk_analyzer.py input.json --dpi 200 --grid_dpi 100
        """
    )
    p.add_argument("input", help="输入 JSON 文件路径")
    p.add_argument("-o", "--out_dir", default="./time_risk_analysis",
                   help="输出目录")
    p.add_argument("--dpi", type=int, default=150,
                   help="matplotlib savefig DPI")
    p.add_argument("--grid_dpi", type=int, default=None,
                   help="每个网格在输出图片中的像素宽度（默认自动计算）")
    p.add_argument("--no-summary", action="store_true",
                   help="不生成摘要文件")
    p.add_argument("--deploy-json", default=None,
                   help="DSSA 部署输出 JSON（含 protection_benefit），用于生成 R-E 散点图")
    return p.parse_args()


def run(input_path: str, out_dir: str = "./time_risk_analysis", dpi: int = 150,
        grid_dpi: int = None, no_summary: bool = False, deploy_json: str = None):
    """Run temporal risk comparison analysis.

    Args:
        input_path: Input JSON file path.
        out_dir: Output directory.
        dpi: matplotlib savefig DPI.
        grid_dpi: Pixels per hex in output image (auto if None).
        no_summary: Skip summary file generation.
        deploy_json: Path to DSSA output JSON (with protection_benefit) for R-E scatter plot.
    """
    print(f"[1/4] Loading input: {input_path}")
    base_data = load_base_input(input_path)

    grids = base_data.get('grids', [])
    hex_size = 1.0
    for g in grids:
        if g.get('hex_size'):
            hex_size = float(g['hex_size'])
            break

    if grid_dpi is None:
        grid_dpi = auto_grid_dpi(grids)

    print(f"  grids: {len(grids)}, hex_size: {hex_size}")
    print(f"  grid_dpi: {grid_dpi}, save_dpi: {dpi}")

    os.makedirs(out_dir, exist_ok=True)

    print(f"\n[2/6] Computing risks for {len(SCENARIOS)} scenarios...")
    scenarios_data = []
    max_raw_risk = 0.0

    for scenario in SCENARIOS:
        print(f"  Computing {scenario['name']}...", end=" ", flush=True)
        norm_map, temporal_map, raw_map = compute_scenario_risk(
            base_data, scenario['hour'], scenario['season']
        )
        scenario_data = {
            "name": scenario["name"],
            "label": scenario["label"],
            "hour": scenario["hour"],
            "season": scenario["season"],
            "period": scenario.get("period", "DAY" if scenario["hour"] == 12 else "NIGHT"),
            "norm_risk_map": norm_map,
            "temporal_factor_map": temporal_map,
            "raw_risk_map": raw_map,
        }
        scenarios_data.append(scenario_data)

        scenario_max = max(raw_map.values())
        scenario_min = min(raw_map.values())
        print(f"raw_risk: [{scenario_min:.4f}, {scenario_max:.4f}]")
        max_raw_risk = max(max_raw_risk, scenario_max)

    print(f"\n[3/6] Generating terrain & species maps...")

    plot_terrain_map(
        grids=grids,
        hex_size=hex_size,
        save_path=os.path.join(out_dir, "terrain_map.png"),
        grid_dpi=grid_dpi,
        save_dpi=dpi,
    )

    plot_species_density_map(
        grids=grids,
        hex_size=hex_size,
        save_path=os.path.join(out_dir, "species_density_map.png"),
        grid_dpi=grid_dpi,
        save_dpi=dpi,
    )
    plot_species_density_panels(
        grids=grids,
        hex_size=hex_size,
        save_path=os.path.join(out_dir, "species_density_panels.png"),
        grid_dpi=grid_dpi,
        save_dpi=dpi,
    )

    print(f"\n[4/6] Generating heatmaps...")
    print(f"  Unified colorbar range: [0, 1]")

    norm_norm = Normalize(vmin=0, vmax=1)

    for scenario in scenarios_data:
        name = scenario["name"]
        norm_map = scenario["norm_risk_map"]
        raw_map = scenario["raw_risk_map"]

        plot_single_risk_heatmap(
            grids=grids,
            risk_map=norm_map,
            hex_size=hex_size,
            title=f"{scenario['label']} - Normalized Risk",
            cmap_norm=norm_norm,
            save_path=os.path.join(out_dir, f"{name}_normalized_risk.png"),
            save_dpi=dpi,
            grid_dpi=grid_dpi
        )

        plot_single_risk_heatmap(
            grids=grids,
            risk_map=raw_map,
            hex_size=hex_size,
            title=f"{scenario['label']} - Raw Risk",
            cmap_norm=Normalize(vmin=0, vmax=1),
            save_path=os.path.join(out_dir, f"{name}_raw_risk.png"),
            save_dpi=dpi,
            grid_dpi=grid_dpi
        )

    print(f"\n[5/6] Generating 4-panel comparison...")
    diurnal_mode_cfg = base_data.get("risk_model_config", {}).get("temporal_weights", {}).get("diurnal_mode", "discrete")
    plot_4panel_comparison(
        scenarios_data=scenarios_data,
        grids=grids,
        hex_size=hex_size,
        max_raw_risk=max_raw_risk,
        save_path=os.path.join(out_dir, "risk_comparison_4panel.png"),
        save_dpi=dpi,
        grid_dpi=grid_dpi,
        diurnal_mode=diurnal_mode_cfg
    )

    protection_ratio = None
    if deploy_json and os.path.exists(deploy_json):
        print(f"\n[6/6] Generating R-E scatter plot (Risk vs Protection)...")
        with open(deploy_json, 'r', encoding='utf-8') as f:
            deploy_data = json.load(f)
        dep_grids = {g['grid_id']: g for g in deploy_data.get('grids', [])}
        protection_ratio = {}
        for g in grids:
            gid = g['grid_id']
            dg = dep_grids.get(gid, {})
            rn = dg.get('risk_normalized', 0.0)
            pb = dg.get('protection_benefit_raw', 0.0)
            if rn > 1e-8:
                ratio = pb / rn
                protection_ratio[gid] = min(max(ratio, 0.0), 1.0)
            else:
                protection_ratio[gid] = 0.0
        plot_re_scatter_4panel(
            scenarios_data=scenarios_data,
            grids=grids,
            protection_ratio=protection_ratio,
            save_path=os.path.join(out_dir, "re_scatter_4panel.png"),
            save_dpi=dpi,
        )
    else:
        print(f"\n[6/6] Skipping R-E scatter plot (--deploy-json not provided)")

    if not no_summary:
        generate_summary(
            scenarios_data=scenarios_data,
            grids=grids,
            save_path=os.path.join(out_dir, "time_risk_summary.txt")
        )

    print(f"\n{'=' * 60}")
    print(f"  完成！输出目录: {os.path.abspath(out_dir)}")
    print(f"{'=' * 60}")
    print("\n生成的文件:")
    print("  地形图:")
    print("    - terrain_map.png")
    print("  物种密度图:")
    print("    - species_density_map.png")
    print("  归一化风险图:")
    for s in SCENARIOS:
        print(f"    - {s['name']}_normalized_risk.png")
    print("  原始风险图:")
    for s in SCENARIOS:
        print(f"    - {s['name']}_raw_risk.png")
    print("  四象限对比图:")
    print(f"    - risk_comparison_4panel.png")
    if protection_ratio is not None:
        print("  R-E 散点图(风险-防护匹配):")
        print(f"    - re_scatter_4panel.png")
    if not no_summary:
        print("  摘要文件:")
        print(f"    - time_risk_summary.txt")


def main():
    args = parse_args()
    run(
        input_path=args.input,
        out_dir=args.out_dir,
        dpi=args.dpi,
        grid_dpi=args.grid_dpi,
        no_summary=args.no_summary,
        deploy_json=args.deploy_json,
    )


if __name__ == "__main__":
    main()
