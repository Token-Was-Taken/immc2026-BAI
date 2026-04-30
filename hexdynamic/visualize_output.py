"""
visualize_output.py
输入：protection_pipeline.py 生成的 output JSON（+ 可选的 input JSON 用于物种数据）
输出：5 张图片
  1. risk_heatmap.png           — 风险热力图
  2. protection_heatmap.png     — 保护收益热力图 + 资源部署叠加
  3. terrain_map.png            — 地理属性地图
  4. terrain_deployment_map.png — 地形 + 部署资源叠加
  5. species_map.png            — 物种密度地图

图例和文字说明全部放在地图右侧独立区域，不遮挡地图。

用法：
    python visualize_output.py output.json
    python visualize_output.py output.json --input input.json --out_dir ./figures
"""

import argparse
import json
import math
import os
from typing import Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from matplotlib.patches import Polygon
from matplotlib.colors import Normalize
from matplotlib import cm


# ---------------------------------------------------------------------------
# 六边形几何
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------

def load_data(output_path, input_path=None):
    with open(output_path, "r", encoding="utf-8") as f:
        out = json.load(f)
    inp = None
    if input_path and os.path.exists(input_path):
        with open(input_path, "r", encoding="utf-8") as f:
            inp = json.load(f)

    hex_size = 1.0
    for g in out["grids"]:
        if g.get("hex_size"):
            hex_size = float(g["hex_size"])
            break

    out_map = {g["grid_id"]: g for g in out["grids"]}
    species_map = {}
    if inp:
        for g in inp.get("grids", []):
            if "species_densities" in g:
                species_map[g["grid_id"]] = g["species_densities"]

    # 提取 boundary_locations，兼容 [{x,y,original_grid_id},...] 和 [[x,y],...] 两种格式
    boundary_xy = None
    if inp and "map_config" in inp:
        bl = inp["map_config"].get("boundary_locations")
        if bl:
            boundary_xy = []
            for item in bl:
                if isinstance(item, dict):
                    boundary_xy.append((item['x'], item['y']))
                else:
                    boundary_xy.append(tuple(item))

    return out, out_map, species_map, hex_size, boundary_xy


# ---------------------------------------------------------------------------
# 布局辅助：地图 ax 设置 + 右侧图例 ax
# ---------------------------------------------------------------------------

def make_figure(has_colorbar=False):
    """
    返回 (fig, ax_map, ax_cbar_or_None, ax_legend)
    has_colorbar=True  → 三列：地图 | 颜色条 | 图例
    has_colorbar=False → 两列：地图 | 图例
    """
    fig = plt.figure(figsize=(14, 9))
    if has_colorbar:
        # 地图 70%，颜色条 3%（紧贴地图），图例 20%，留白 2%+5%
        ax_map  = fig.add_axes([0.02, 0.06, 0.68, 0.86])
        ax_cbar = fig.add_axes([0.72, 0.12, 0.025, 0.62])
        ax_leg  = fig.add_axes([0.77, 0.06, 0.21, 0.86])
    else:
        ax_map  = fig.add_axes([0.02, 0.06, 0.76, 0.86])
        ax_cbar = None
        ax_leg  = fig.add_axes([0.80, 0.06, 0.18, 0.86])
    ax_map.set_aspect("equal")
    ax_map.axis("off")
    ax_leg.axis("off")
    return fig, ax_map, ax_cbar, ax_leg


def setup_map_ax(ax, grids, hex_size, margin=1.5):
    xs, ys = [], []
    for g in grids:
        cx, cy = grid_center(g["q"], g["r"], hex_size)
        xs.append(cx); ys.append(cy)
    ax.set_xlim(min(xs) - hex_size - margin, max(xs) + hex_size + margin)
    ax.set_ylim(min(ys) - hex_size - margin, max(ys) + hex_size + margin)
    ax.set_aspect('equal')


def draw_boundary(ax, grids, boundary_xy, hex_size):
    """
    在边界格子的外侧边上画保护区轮廓线。
    boundary_xy: [(x, y), ...] 边界格子的笛卡尔坐标（来自 input JSON）
    通过 x/y 匹配 grids 里的格子，找到对应的 q/r，再找出朝向保护区外的六边形边绘制。
    """
    if not boundary_xy:
        return

    # 建立 (x, y) → grid 的映射
    xy_to_grid = {(g["x"], g["y"]): g for g in grids}
    # 保护区内所有格子的 (q, r) 集合
    inner_qr = {(g["q"], g["r"]) for g in grids}

    # pointy-top 六边形的 6 个邻居方向（axial 坐标偏移）
    # 对应边的两个顶点角度索引（顶点从 -30° 开始，每 60° 一个）
    # 方向顺序：E, NE, NW, W, SW, SE
    neighbor_dirs = [(1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1)]
    # 每个方向对应的外侧边顶点索引（pointy-top，顶点 i 在角度 60*i - 30 度）
    # FIX: Rotate direction mapping to match actual deployment
    dir_to_edge_verts = {
        (1,  0): (1, 0),   # E  → 顶点 1,0
        (0,  1): (2, 1),   # NE → 顶点 2,1
        (-1, 1): (3, 2),   # NW → 顶点 3,2
        (-1, 0): (4, 3),   # W  → 顶点 4,3
        (0, -1): (5, 4),   # SW → 顶点 5,4
        (1, -1): (0, 5),   # SE → 顶点 0,5
    }

    def get_corner(cx, cy, size, i):
        a = math.pi / 3 * i - math.pi / 6
        return cx + size * math.cos(a), cy + size * math.sin(a)

    for bx, by in boundary_xy:
        g = xy_to_grid.get((bx, by))
        if g is None:
            continue
        q, r = g["q"], g["r"]
        cx, cy = grid_center(q, r, hex_size)
        for (dq, dr), (vi, vj) in zip(neighbor_dirs, dir_to_edge_verts.values()):
            nq, nr = q + dq, r + dr
            if (nq, nr) not in inner_qr:
                # 这条边朝向保护区外，画轮廓线
                p1 = get_corner(cx, cy, hex_size, vi)
                p2 = get_corner(cx, cy, hex_size, vj)
                ax.plot([p1[0], p2[0]], [p1[1], p2[1]],
                        color="#1a1a1a", lw=1.8, zorder=6, solid_capstyle="round")


def draw_deployed_fence_edges(ax, grids, out, hex_size, color=None):
    """
    Draw deployed fence edges as bold lines on the map.
    
    Each fence edge is drawn as a thick line segment between
    the two grid centers or from grid center to boundary.
    
    Args:
        ax: Matplotlib axes to draw on
        grids: List of grid dictionaries from output JSON
        out: Output JSON data containing fence_edges or per-grid fences
        hex_size: Size of hexagonal grid cells
        color: Optional color for fence edges (defaults to FENCE_COLOR)
    """
    if color is None:
        color = FENCE_COLOR
    fence_edges = out.get("fence_edges", [])
    # If no global fence_edges, build from per-grid boundary_edge_list
    if not fence_edges:
        fence_edges = []
        for g in grids:
            if "fences" in g and "boundary_edge_list" in g["fences"]:
                for dir_idx in g["fences"]["boundary_edge_list"]:
                    fence_edges.append({
                        "grid_id_1": g["grid_id"],
                        "grid_id_2": None,
                        "direction": dir_idx
                    })
        if not fence_edges:
            return
    
    # Build grid lookup
    grid_by_id = {g["grid_id"]: g for g in grids}
    
    # Build set of all grid IDs for checking if a neighbor exists
    all_grid_ids = set(grid_by_id.keys())
    
    # Hexagonal directions (same as used in grid_model.py)
    # Direction mapping for pointy-topped hexagons:
    # 0: (1, 0)   - East
    # 1: (0, 1)   - Northeast
    # 2: (-1, 1)  - Northwest
    # 3: (-1, 0)  - West
    # 4: (0, -1)  - Southwest
    # 5: (1, -1)  - Southeast
    directions = [
        (1, 0),   # 0: East
        (0, 1),   # 1: Northeast
        (-1, 1),  # 2: Northwest
        (-1, 0),  # 3: West
        (0, -1),  # 4: Southwest
        (1, -1)   # 5: Southeast
    ]
    
    # Each direction corresponds to an edge between two corner vertices
    # For pointy-topped hexagon, corners are at angles: 30, 90, 150, 210, 270, 330 degrees
    # Direction -> (corner_index_start, corner_index_end)
    # FIX: Rotate direction mapping to match actual deployment
    dir_to_corners = {
        0: (1, 0),  # East: corners 1 and 0
        1: (2, 1),  # Northeast: corners 2 and 1
        2: (3, 2),  # Northwest: corners 3 and 2
        3: (4, 3),  # West: corners 4 and 3
        4: (5, 4),  # Southwest: corners 5 and 4
        5: (0, 5),  # Southeast: corners 0 and 5
    }
    
    def get_corner(cx, cy, size, i):
        """Get corner coordinates for pointy-topped hexagon."""
        # Corners at 30, 90, 150, 210, 270, 330 degrees (pointy-top)
        # FIX: Use same angle calculation as draw_boundary function
        a = math.pi / 3 * i - math.pi / 6
        return cx + size * math.cos(a), cy + size * math.sin(a)
    
    drawn_edges = set()  # Track drawn edges to avoid duplicates
    
    # Count for debugging
    boundary_edge_count = 0
    internal_edge_skipped = 0
    
    for edge in fence_edges:
        grid_id_1 = edge.get("grid_id_1")
        grid_id_2 = edge.get("grid_id_2")
        direction = edge.get("direction")  # May be None for internal edges
        
        if grid_id_1 is None:
            continue
            
        g1 = grid_by_id.get(grid_id_1)
        if g1 is None:
            continue
        
        cx1, cy1 = grid_center(g1["q"], g1["r"], hex_size)
        
        # FIX: Only draw boundary edges (where grid_id_2 is None or not in grid set)
        # Fences can ONLY be deployed on boundary edges, not internal edges between grids
        if grid_id_2 is not None and grid_id_2 in all_grid_ids:
            # Internal edge between two grids - SKIP (not a valid fence location)
            internal_edge_skipped += 1
            continue
        
        # Boundary edge (facing outside) - this is a valid fence location
        # Use direction if provided, otherwise try to determine from edge data
        if direction is not None:
            edge_key = (grid_id_1, None, direction)
            if edge_key in drawn_edges:
                continue
            drawn_edges.add(edge_key)
            
            vi, vj = dir_to_corners[direction]
            p1 = get_corner(cx1, cy1, hex_size, vi)
            p2 = get_corner(cx1, cy1, hex_size, vj)
            ax.plot([p1[0], p2[0]], [p1[1], p2[1]],
                        color=color, lw=FENCE_EDGE_LINEWIDTH, zorder=7,
                        solid_capstyle="round")
            boundary_edge_count += 1
        else:
            # No direction provided - try to determine from grid_id_2 being None
            # This handles the case where grid_id_2 is None (boundary edge)
            edge_key = (grid_id_1, None)
            if edge_key in drawn_edges:
                continue
            drawn_edges.add(edge_key)
            
            # For boundary edges without direction, we need to find which edge faces outside
            # Check each direction to find the one without a neighbor
            for dir_idx in range(6):
                dq, dr = directions[dir_idx]
                neighbor_q = g1["q"] + dq
                neighbor_r = g1["r"] + dr
                neighbor_key = (neighbor_q, neighbor_r)
                
                # Check if this neighbor exists in our grid set
                neighbor_id = None
                for gid, g in grid_by_id.items():
                    if g["q"] == neighbor_q and g["r"] == neighbor_r:
                        neighbor_id = gid
                        break
                
                if neighbor_id is None:
                    # This is a boundary direction - draw the edge
                    vi, vj = dir_to_corners[dir_idx]
                    p1 = get_corner(cx1, cy1, hex_size, vi)
                    p2 = get_corner(cx1, cy1, hex_size, vj)
                    ax.plot([p1[0], p2[0]], [p1[1], p2[1]],
                            color=FENCE_COLOR, lw=FENCE_EDGE_LINEWIDTH, zorder=7,
                            solid_capstyle="round")
                    boundary_edge_count += 1
    
    # Debug output
    if fence_edges:
        print(f"[DEBUG] Fence edge visualization:")
        print(f"  - Total fence edges in data: {len(fence_edges)}")
        print(f"  - Boundary edges drawn: {boundary_edge_count}")
        print(f"  - Internal edges skipped: {internal_edge_skipped}")


def legend_in_ax(ax_leg, handles, title, y_start=1.0, fontsize=9, title_fontsize=9):
    """在 ax_leg 里手动绘制图例，返回下一个可用 y 位置"""
    ax_leg.text(0.05, y_start, title, transform=ax_leg.transAxes,
                fontsize=title_fontsize, fontweight="bold", va="top")
    y = y_start - 0.06
    for h in handles:
        # 画色块或线条
        if isinstance(h, mpatches.Patch):
            rect = mpatches.FancyBboxPatch((0.05, y - 0.025), 0.12, 0.04,
                                           boxstyle="square,pad=0",
                                           facecolor=h.get_facecolor(),
                                           edgecolor="black", linewidth=0.5,
                                           transform=ax_leg.transAxes, clip_on=False)
            ax_leg.add_patch(rect)
        else:
            # Line2D with marker
            marker = h.get_marker()
            mfc = h.get_markerfacecolor()
            mec = h.get_markeredgecolor()
            ax_leg.plot(0.11, y - 0.005, marker=marker, color="w",
                        markerfacecolor=mfc, markeredgecolor=mec,
                        markersize=8, transform=ax_leg.transAxes,
                        clip_on=False)
        ax_leg.text(0.22, y - 0.005, h.get_label(), transform=ax_leg.transAxes,
                    fontsize=fontsize, va="center")
        y -= 0.055
    return y - 0.02


def add_colorbar(fig, ax_cbar, cmap, norm, label):
    """在专用的 ax_cbar 上绘制颜色条"""
    sm = cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cb = fig.colorbar(sm, cax=ax_cbar)
    cb.set_label(label, fontsize=9)
    cb.ax.tick_params(labelsize=8)


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

TERRAIN_COLORS = {
    "SparseGrass": "#a8d5a2",
    "DenseGrass":  "#2d6a2d",
    "WaterHole":   "#5b9bd5",
    "SaltMarsh":   "#c8b97a",
    "Road":        "#888888",
}

RESOURCE_MARKERS = {
    "camera":         ("s", "#1f77b4", "Camera"),
    "drone":          ("^", "#ff7f0e", "Drone"),
    "camp":           ("D", "#9467bd", "Camp"),
    "patrol_rangers": ("o", "#2ca02c", "Patrol"),
}

FENCE_COLOR = "#c0392b"
FENCE_EDGE_LINEWIDTH = 3.0  # Thicker for better visibility

SPECIES_STYLE = {
    "rhino":    {"marker": "^", "color": "#8B4513", "size_scale": 120},
    "elephant": {"marker": "s", "color": "#708090", "size_scale": 120},
    "bird":     {"marker": "o", "color": "#FF6347",  "size_scale": 80},
}


def _edge_grid_ids(grids, boundary_xy=None):
    """
    返回边缘网格的ID集合
    
    如果提供了boundary_xy，使用实际的边界网格
    否则使用矩形边界的边缘网格（向后兼容）
    """
    if boundary_xy:
        # 使用实际的边界网格
        xy_to_grid = {(g["x"], g["y"]): g for g in grids}
        return {xy_to_grid[(x, y)]["grid_id"] for (x, y) in boundary_xy if (x, y) in xy_to_grid}
    else:
        # 使用矩形边界的边缘网格（旧逻辑）
        rows = [g["r"] for g in grids]
        cols = [g["q"] + g["r"] // 2 for g in grids]
        min_r, max_r = min(rows), max(rows)
        min_c, max_c = min(cols), max(cols)
        return {g["grid_id"] for g in grids
                if g["r"] in (min_r, max_r) or (g["q"] + g["r"] // 2) in (min_c, max_c)}


def _draw_resources(ax, grids, out, hex_size, edge_ids):
    """在 ax 上绘制所有资源图标（除了围栏，围栏用加粗边显示）
    
    围栏只在实际部署的边上显示（用加粗边），不再用五边形在网格内显示
    """
    # NOTE: Fence deployment is now shown with bold edges in draw_deployed_fence_edges()
    # No need to draw pentagon markers inside grid cells
    
    centers = {g["grid_id"]: grid_center(g["q"], g["r"], hex_size) for g in grids}

    for g in grids:
        cx, cy = centers[g["grid_id"]]
        dep = g["deployment"]
        offset = 0
        for key, (marker, color, _) in RESOURCE_MARKERS.items():
            val = dep.get(key, 0)
            if val > 0:
                ox = (offset - 1) * hex_size * 0.28
                ax.scatter(cx + ox, cy, marker=marker, s=60, color=color,
                           edgecolors="black", linewidths=0.5, zorder=5)
                if val > 1:
                    ax.text(cx + ox, cy + hex_size * 0.35, str(val),
                            ha="center", va="bottom", fontsize=6, color=color, zorder=6)
                offset += 1


# ---------------------------------------------------------------------------
# 图 1：风险热力图
# ---------------------------------------------------------------------------

def plot_risk_heatmap(out, out_map, hex_size, boundary_xy, save_path):
    grids = out["grids"]
    summary = out["summary"]
    cmap = matplotlib.colormaps.get_cmap("YlOrRd")
    norm = Normalize(vmin=0, vmax=1)

    fig, ax, ax_cbar, ax_leg = make_figure(has_colorbar=True)

    for g in grids:
        cx, cy = grid_center(g["q"], g["r"], hex_size)
        draw_hex(ax, cx, cy, hex_size * 0.97, facecolor=cmap(norm(g["risk_normalized"])))
        # 添加网格 ID 标注
        ax.text(cx, cy, str(g["grid_id"]), ha="center", va="center", fontsize=6, zorder=4)

    setup_map_ax(ax, grids, hex_size)
    draw_boundary(ax, grids, boundary_xy, hex_size)
    ax.set_title("Risk Heatmap", fontsize=13, fontweight="bold", pad=8)

    add_colorbar(fig, ax_cbar, cmap, norm, "Normalized Risk")

    risk_vals = [g["risk_normalized"] for g in grids]
    items = [
        ("Summary",     None,                                           True),
        ("Total Grids", str(summary['total_grids']),                    False),
        ("Risk Min",    f"{min(risk_vals):.4f}",                        False),
        ("Risk Max",    f"{max(risk_vals):.4f}",                        False),
        ("Risk Mean",   f"{sum(risk_vals)/len(risk_vals):.4f}",         False),
        ("Total Risk",  f"{summary.get('total_risk', sum(risk_vals)):.4f}", False),
    ]
    y = 0.97
    for label, value, bold in items:
        text = label if value is None else f"{label}: {value}"
        ax_leg.text(0.05, y, text, transform=ax_leg.transAxes,
                    fontsize=9, va="top",
                    fontweight="bold" if bold else "normal",
                    fontfamily="monospace")
        y -= 0.09

    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved: {save_path}")


def plot_protection_heatmap(out, hex_size, boundary_xy, save_path):
    grids = out["grids"]
    summary = out["summary"]
    cmap = matplotlib.colormaps.get_cmap("Greens")

    summary_items = [
        ("Best Fitness", f"{summary['best_fitness']:.4f}"),
        ("Total PB",     f"{summary['total_protection_benefit']:.4f}"),
        ("Avg PB",       f"{summary['average_protection_benefit']:.4f}"),
    ]

    def _draw(title, value_key, vmax, path):
        norm = Normalize(vmin=0, vmax=vmax if vmax > 0 else 1)
        fig, ax, ax_cbar, ax_leg = make_figure(has_colorbar=True)

        for g in grids:
            cx, cy = grid_center(g["q"], g["r"], hex_size)
            draw_hex(ax, cx, cy, hex_size * 0.97, facecolor=cmap(norm(g.get(value_key, 0))))
            # 添加网格 ID 标注
            ax.text(cx, cy, str(g["grid_id"]), ha="center", va="center", fontsize=6, zorder=4)

        setup_map_ax(ax, grids, hex_size)
        draw_boundary(ax, grids, boundary_xy, hex_size)
        ax.set_title(title, fontsize=13, fontweight="bold", pad=8)
        add_colorbar(fig, ax_cbar, cmap, norm, f"Protection Benefit ({value_key.split('_')[-1]})")

        y = 0.97
        ax_leg.text(0.05, y, "Summary", transform=ax_leg.transAxes,
                    fontsize=9, fontweight="bold", va="top")
        y -= 0.09
        for k, v in summary_items:
            ax_leg.text(0.05, y, f"{k}: {v}", transform=ax_leg.transAxes,
                        fontsize=8, va="top", fontfamily="monospace")
            y -= 0.09

        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"  saved: {path}")

    # Normalized
    norm_max = max((g.get("protection_benefit_normalized", 0) for g in grids), default=1)
    _draw("Protection Benefit (Normalized)", "protection_benefit_normalized",
          norm_max, save_path)

    # Raw — derive save path by inserting _raw before extension
    base, ext = os.path.splitext(save_path)
    raw_path = f"{base}_raw{ext}"
    raw_max = max((g.get("protection_benefit_raw", 0) for g in grids), default=1)
    _draw("Protection Benefit (Raw)", "protection_benefit_raw",
          raw_max, raw_path)


def plot_risk_comparison(out, hex_size, boundary_xy, save_path):
    """上下对比：部署前风险（risk_normalized）vs 部署后剩余风险（residual_risk_normalized）"""
    grids = out["grids"]
    summary = out["summary"]

    # 检查是否有 residual_risk_normalized 字段
    if not grids or "residual_risk_normalized" not in grids[0]:
        print("  [skip] risk_comparison.png — 输出数据缺少 residual_risk_normalized 字段")
        return

    cmap = matplotlib.colormaps.get_cmap("YlOrRd")

    # 先计算两侧数据，确定统一的颜色条上限
    risk_before = [g["risk_normalized"] for g in grids]
    risk_after  = [g["residual_risk_normalized"] for g in grids]
    vmax = max(max(risk_before), max(risk_after))
    norm = Normalize(vmin=0, vmax=vmax)

    fig = plt.figure(figsize=(14, 16))
    # 颜色条在最左边，然后是两个热力图上下排列，summary在最右边
    ax_cbar   = fig.add_axes([0.02, 0.12, 0.02, 0.70])
    ax_before = fig.add_axes([0.07, 0.52, 0.70, 0.42])
    ax_after  = fig.add_axes([0.07, 0.05, 0.70, 0.42])
    ax_leg    = fig.add_axes([0.80, 0.05, 0.18, 0.90])

    for ax in (ax_before, ax_after):
        ax.set_aspect("equal")
        ax.axis("off")
    ax_leg.axis("off")

    for g in grids:
        cx, cy = grid_center(g["q"], g["r"], hex_size)
        draw_hex(ax_before, cx, cy, hex_size * 0.97,
                 facecolor=cmap(norm(g["risk_normalized"])))
        draw_hex(ax_after, cx, cy, hex_size * 0.97,
                 facecolor=cmap(norm(g["residual_risk_normalized"])))
        # 在两个子图上都添加网格 ID 标注
        ax_before.text(cx, cy, str(g["grid_id"]), ha="center", va="center", fontsize=6, zorder=4)
        ax_after.text(cx, cy, str(g["grid_id"]), ha="center", va="center", fontsize=6, zorder=4)

    setup_map_ax(ax_before, grids, hex_size)
    setup_map_ax(ax_after, grids, hex_size)
    draw_boundary(ax_before, grids, boundary_xy, hex_size)
    draw_boundary(ax_after, grids, boundary_xy, hex_size)

    ax_before.set_title("Before Deployment\n(Normalized Risk)", fontsize=12, fontweight="bold", pad=8)
    ax_after.set_title("After Deployment\n(Residual Risk)", fontsize=12, fontweight="bold", pad=8)

    sm = cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cb = fig.colorbar(sm, cax=ax_cbar)
    cb.set_label("Risk Level", fontsize=9)
    cb.ax.tick_params(labelsize=8)

    # 右侧指标：展示保护前后的风险统计
    n = len(grids)
    mean_before = sum(risk_before) / n
    mean_after  = sum(risk_after) / n
    reduction   = (mean_before - mean_after) / mean_before * 100 if mean_before > 0 else 0

    items = [
        ("Summary",        None,                          True),
        ("Total Grids",    str(summary['total_grids']),   False),
        ("--- Before ---", None,                          True),
        ("Risk Min",       f"{min(risk_before):.4f}",     False),
        ("Risk Max",       f"{max(risk_before):.4f}",     False),
        ("Risk Mean",      f"{mean_before:.4f}",          False),
        ("--- After ---",  None,                          True),
        ("Risk Min",       f"{min(risk_after):.4f}",      False),
        ("Risk Max",       f"{max(risk_after):.4f}",      False),
        ("Risk Mean",      f"{mean_after:.4f}",           False),
        ("--- Delta ---",  None,                          True),
        ("Reduction",      f"{reduction:.1f}%",           False),
        ("Fitness",        f"{summary['best_fitness']:.4f}", False),
    ]
    y = 0.97
    for label, value, bold in items:
        text = label if value is None else f"{label}: {value}"
        ax_leg.text(0.05, y, text, transform=ax_leg.transAxes,
                    fontsize=8, va="top",
                    fontweight="bold" if bold else "normal",
                    fontfamily="monospace")
        y -= 0.07

    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved: {save_path}")


def plot_terrain_map(out, hex_size, boundary_xy, save_path):
    grids = out["grids"]
    fig, ax, _, ax_leg = make_figure(has_colorbar=False)

    for g in grids:
        cx, cy = grid_center(g["q"], g["r"], hex_size)
        draw_hex(ax, cx, cy, hex_size * 0.97, facecolor=TERRAIN_COLORS.get(g["terrain_type"], "#ccc"))
        # 添加网格 ID 标注
        ax.text(cx, cy, str(g["grid_id"]), ha="center", va="center", fontsize=6, zorder=4)

    draw_deployed_fence_edges(ax, grids, out, hex_size, color="#1a1a1a")
    setup_map_ax(ax, grids, hex_size)
    draw_boundary(ax, grids, boundary_xy, hex_size)
    ax.set_title("Terrain Map", fontsize=13, fontweight="bold", pad=8)

    handles = [mpatches.Patch(facecolor=c, edgecolor="black", linewidth=0.5, label=t)
               for t, c in TERRAIN_COLORS.items()]
    # Add fence handle
    handles.append(
        plt.Line2D([0], [1], color="#1a1a1a", linewidth=FENCE_EDGE_LINEWIDTH * 2, 
                   label="Fence (bold edge)")
    )
    legend_in_ax(ax_leg, handles, "Terrain Type", y_start=0.97)

    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved: {save_path}")


def plot_terrain_deployment_map(out, hex_size, boundary_xy, save_path):
    grids = out["grids"]
    edge_ids = _edge_grid_ids(grids, boundary_xy)
    fig, ax, _, ax_leg = make_figure(has_colorbar=False)

    for g in grids:
        cx, cy = grid_center(g["q"], g["r"], hex_size)
        draw_hex(ax, cx, cy, hex_size * 0.97, facecolor=TERRAIN_COLORS.get(g["terrain_type"], "#ccc"), alpha=0.45)

    _draw_resources(ax, grids, out, hex_size, edge_ids)
    draw_deployed_fence_edges(ax, grids, out, hex_size)
    setup_map_ax(ax, grids, hex_size)
    draw_boundary(ax, grids, boundary_xy, hex_size)
    ax.set_title("Terrain Map with Deployment", fontsize=13, fontweight="bold", pad=8)

    terrain_handles = [mpatches.Patch(facecolor=c, edgecolor="black", linewidth=0.5, alpha=0.5, label=t)
                       for t, c in TERRAIN_COLORS.items()]
    res_handles = [
        plt.Line2D([0], [0], marker=m, color="w", markerfacecolor=c,
                   markeredgecolor="black", markersize=8, label=l)
        for _, (m, c, l) in RESOURCE_MARKERS.items()
    ]
    res_handles.append(
        plt.Line2D([0], [1], color=FENCE_COLOR, linewidth=FENCE_EDGE_LINEWIDTH * 2, 
                   label="Fence (bold edge)")
    )

    y = legend_in_ax(ax_leg, terrain_handles, "Terrain", y_start=0.97)
    legend_in_ax(ax_leg, res_handles, "Resources", y_start=y)

    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved: {save_path}")


def plot_species_map(out, species_map, hex_size, boundary_xy, save_path):
    grids = out["grids"]
    if not species_map:
        print("  [skip] species_map.png — 无物种数据（请提供 --input 参数）")
        return

    all_species = sorted({sp for sd in species_map.values() for sp in sd})
    fig, ax, _, ax_leg = make_figure(has_colorbar=False)

    for g in grids:
        cx, cy = grid_center(g["q"], g["r"], hex_size)
        draw_hex(ax, cx, cy, hex_size * 0.97,
                 facecolor=TERRAIN_COLORS.get(g["terrain_type"], "#ccc"), alpha=0.45)

    for g in grids:
        sd = species_map.get(g["grid_id"], {})
        active = [sp for sp in all_species if sd.get(sp, 0) > 0]
        if not active:
            continue
        cx, cy = grid_center(g["q"], g["r"], hex_size)
        n = len(active)
        for i, sp in enumerate(active):
            style = SPECIES_STYLE.get(sp, {"marker": "P", "color": "#333", "size_scale": 80})
            ox = (i - (n - 1) / 2) * hex_size * 0.35
            size = max(10, style["size_scale"] * sd[sp])
            ax.scatter(cx + ox, cy, marker=style["marker"], s=size,
                       color=style["color"], edgecolors="black",
                       linewidths=0.4, alpha=0.85, zorder=4)

    setup_map_ax(ax, grids, hex_size)
    draw_boundary(ax, grids, boundary_xy, hex_size)
    ax.set_title("Species Density Map", fontsize=13, fontweight="bold", pad=8)

    terrain_handles = [mpatches.Patch(facecolor=c, edgecolor="black", linewidth=0.5, alpha=0.5, label=t)
                       for t, c in TERRAIN_COLORS.items()]
    species_handles = [
        plt.Line2D([0], [0], marker=SPECIES_STYLE.get(sp, {}).get("marker", "P"),
                   color="w",
                   markerfacecolor=SPECIES_STYLE.get(sp, {}).get("color", "#333"),
                   markeredgecolor="black", markersize=9,
                   label=f"{sp} (size ∝ density)")
        for sp in all_species
    ]

    y = legend_in_ax(ax_leg, terrain_handles, "Terrain", y_start=0.97)
    legend_in_ax(ax_leg, species_handles, "Species Density", y_start=y)

    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved: {save_path}")


def plot_species_deployment_comparison(out, species_map, hex_size, boundary_xy, save_path):
    """物种密度与部署资源对比图（上：物种密度，下：部署资源）"""
    grids = out["grids"]

    fig = plt.figure(figsize=(16, 18))
    
    # 上半部分：物种密度
    ax1 = fig.add_axes([0.05, 0.52, 0.7, 0.45])
    
    # 下半部分：部署资源
    ax2 = fig.add_axes([0.05, 0.05, 0.7, 0.45])
    
    # 右侧图例
    ax_leg1 = fig.add_axes([0.78, 0.05, 0.2, 0.9])
    ax_leg1.axis("off")

    # ================= 上半部分：物种密度图
    all_species = []
    if species_map:
        all_species = sorted({sp for sd in species_map.values() for sp in sd})
    
    for g in grids:
        cx, cy = grid_center(g["q"], g["r"], hex_size)
        draw_hex(ax1, cx, cy, hex_size * 0.97,
                 facecolor=TERRAIN_COLORS.get(g["terrain_type"], "#ccc"), alpha=0.45)

    if species_map:
        for g in grids:
            sd = species_map.get(g["grid_id"], {})
            active = [sp for sp in all_species if sd.get(sp, 0) > 0]
            if not active:
                continue
            cx, cy = grid_center(g["q"], g["r"], hex_size)
            n = len(active)
            for i, sp in enumerate(active):
                style = SPECIES_STYLE.get(sp, {"marker": "P", "color": "#333", "size_scale": 80})
                ox = (i - (n - 1) / 2) * hex_size * 0.35
                size = max(10, style["size_scale"] * sd[sp])
                ax1.scatter(cx + ox, cy, marker=style["marker"], s=size,
                           color=style["color"], edgecolors="black",
                           linewidths=0.4, alpha=0.85, zorder=4)

    setup_map_ax(ax1, grids, hex_size)
    draw_boundary(ax1, grids, boundary_xy, hex_size)
    ax1.set_title("Species Density (Top)", fontsize=13, fontweight="bold", pad=8)

    # ================= 下半部分：部署资源图
    for g in grids:
        cx, cy = grid_center(g["q"], g["r"], hex_size)
        draw_hex(ax2, cx, cy, hex_size * 0.97,
                 facecolor=TERRAIN_COLORS.get(g["terrain_type"], "#ccc"), alpha=0.45)

    _draw_resources(ax2, grids, out, hex_size, edge_ids=_edge_grid_ids(grids, boundary_xy))
    draw_deployed_fence_edges(ax2, grids, out, hex_size)
    
    setup_map_ax(ax2, grids, hex_size)
    draw_boundary(ax2, grids, boundary_xy, hex_size)
    ax2.set_title("Deployment (Bottom)", fontsize=13, fontweight="bold", pad=8)

    # ================= 右侧图例
    terrain_handles = [mpatches.Patch(facecolor=c, edgecolor="black", linewidth=0.5, alpha=0.5, label=t)
                       for t, c in TERRAIN_COLORS.items()]
    res_handles = [
        plt.Line2D([0], [0], marker=m, color="w", markerfacecolor=c,
                   markeredgecolor="black", markersize=8, label=l)
        for _, (m, c, l) in RESOURCE_MARKERS.items()
    ]
    res_handles.append(
        plt.Line2D([0], [1], color=FENCE_COLOR, linewidth=FENCE_EDGE_LINEWIDTH * 2,
                   label="Fence (bold edge)")
    )

    y = legend_in_ax(ax_leg1, terrain_handles, "Terrain", y_start=0.97)
    y = legend_in_ax(ax_leg1, res_handles, "Resources", y_start=y)

    if species_map:
        species_handles = [
            plt.Line2D([0], [0], marker=SPECIES_STYLE.get(sp, {}).get("marker", "P"),
                       color="w",
                       markerfacecolor=SPECIES_STYLE.get(sp, {}).get("color", "#333"),
                       markeredgecolor="black", markersize=9,
                       label=f"{sp} (size ∝ density)")
            for sp in all_species
        ]
        legend_in_ax(ax_leg1, species_handles, "Species Density", y_start=y)

    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved: {save_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="可视化 protection_pipeline.py 的输出 JSON",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("output", help="pipeline 输出 JSON 路径")
    p.add_argument("--input", "-i", default=None, help="pipeline 输入 JSON 路径（用于物种数据）")
    p.add_argument("--out_dir", "-d", default="./figures", help="图片输出目录")
    p.add_argument("--prefix", default="", help="输出文件名前缀")
    return p.parse_args()


def main():
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    print(f"加载数据: {args.output}")
    out, out_map, species_map, hex_size, boundary_xy = load_data(args.output, args.input)
    print(f"  网格数: {len(out['grids'])}, hex_size: {hex_size}")
    if boundary_xy:
        print(f"  边界格子数: {len(boundary_xy)}")

    pre = args.prefix + "_" if args.prefix else ""
    print("生成图片...")

    plot_risk_heatmap(out, out_map, hex_size, boundary_xy,
                      save_path=os.path.join(args.out_dir, f"{pre}risk_heatmap.png"))
    plot_risk_comparison(out, hex_size, boundary_xy,
                         save_path=os.path.join(args.out_dir, f"{pre}risk_comparison.png"))
    plot_protection_heatmap(out, hex_size, boundary_xy,
                            save_path=os.path.join(args.out_dir, f"{pre}protection_heatmap.png"))
    plot_terrain_map(out, hex_size, boundary_xy,
                     save_path=os.path.join(args.out_dir, f"{pre}terrain_map.png"))
    plot_terrain_deployment_map(out, hex_size, boundary_xy,
                                save_path=os.path.join(args.out_dir, f"{pre}terrain_deployment_map.png"))
    plot_species_map(out, species_map, hex_size, boundary_xy,
                     save_path=os.path.join(args.out_dir, f"{pre}species_map.png"))
    
    plot_species_deployment_comparison(out, species_map, hex_size, boundary_xy,
                                      save_path=os.path.join(args.out_dir, f"{pre}species_deployment_comparison.png"))
    print("完成。")


if __name__ == "__main__":
    main()
