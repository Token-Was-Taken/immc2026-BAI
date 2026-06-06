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
# Disable the "more than 20 figures" warning
matplotlib.rcParams["figure.max_open_warning"] = 0
matplotlib.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": [
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "Arial Unicode MS",
        "DejaVu Sans",
    ],
    "axes.titlesize": 13,
    "axes.labelsize": 10,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 9,
})
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from matplotlib.patches import Polygon
from matplotlib.colors import Normalize, LinearSegmentedColormap
from matplotlib import cm


FIG_BG_COLOR = "#f6f8fb"
MAP_BG_COLOR = "#f2f5f7"
PANEL_BG_COLOR = "#ffffff"
PANEL_EDGE_COLOR = "#d0d7de"
TEXT_COLOR = "#1f2933"
SUBTLE_TEXT_COLOR = "#5f6b7a"
HEX_EDGE_COLOR = "#253542"
BOUNDARY_COLOR = "#172b38"
BOUNDARY_LINEWIDTH = 1.6
RISK_CMAP = LinearSegmentedColormap.from_list(
    "risk_rag",
    ["#1a9850", "#fee08b", "#d73027"],
    N=256,
)


# ---------------------------------------------------------------------------
# 鍏竟褰㈠嚑浣?
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


def draw_hex_batch(ax, grids, hex_size, facecolors, scale=0.97, edgecolor="black", lw=0.3, alpha=1.0):
    """Draw hexagons in batch with PatchCollection for speed."""
    from matplotlib.patches import Polygon
    from matplotlib.collections import PatchCollection
    patches = []
    for g in grids:
        cx, cy = grid_center(g["q"], g["r"], hex_size)
        corners = hex_corners(cx, cy, hex_size * scale)
        patches.append(Polygon(corners, closed=True))
    pc = PatchCollection(patches, facecolors=facecolors,
                         edgecolors=edgecolor, linewidths=lw, alpha=alpha)
    ax.add_collection(pc)


def style_figure(fig):
    fig.patch.set_facecolor(FIG_BG_COLOR)


def style_map_ax(ax):
    ax.set_facecolor(MAP_BG_COLOR)
    ax.axis("off")
    ax.set_aspect("equal")


def style_panel_ax(ax):
    ax.set_facecolor(PANEL_BG_COLOR)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_color(PANEL_EDGE_COLOR)
        spine.set_linewidth(0.8)


# ---------------------------------------------------------------------------
# 鏁版嵁鍔犺浇
# ---------------------------------------------------------------------------

def load_data(output_path=None, input_path=None):
    """
    鍔犺浇 input/output JSON 鏁版嵁銆?

    鏀寔涓夌妯″紡锛?
      1. output_path + input_path锛氬畬鏁存ā寮忥紝output 鐢ㄤ簬閮ㄧ讲/淇濇姢鍥撅紝input 鐢ㄤ簬椋庨櫓/鐗╃/鍦板舰鍥?
      2. output_path only锛歰utput 鍚屾椂鍏呭綋 input锛堝吋瀹规棫閫昏緫锛?
      3. input_path only锛氫粎 input 妯″紡锛屽彧鐢熸垚椋庨櫓/鐗╃/鍦板舰鍥?

    杩斿洖: (input_data, output_data, grid_map, species_map, hex_size, boundary_xy)
      - input_data: input JSON 鍘熷鏁版嵁锛堝惈 risk_normalized, species_densities, terrain_type 绛夛級
      - output_data: output JSON 鍘熷鏁版嵁锛堝惈 deployment, protection_benefit 绛夛級锛屾棤 output 鏃朵负 None
      - grid_map: {grid_id: grid_dict} 鍩轰簬 input_data
      - species_map: {grid_id: species_densities}
      - hex_size: 鍏竟褰㈠ぇ灏?
      - boundary_xy: 杈圭晫鍧愭爣鍒楄〃
    """
    inp = None
    out = None

    if input_path and os.path.exists(input_path):
        with open(input_path, "r", encoding="utf-8") as f:
            inp = json.load(f)

    if output_path and os.path.exists(output_path):
        with open(output_path, "r", encoding="utf-8") as f:
            out = json.load(f)

    # 濡傛灉鍙彁渚涗簡涓€涓枃浠讹紝鑷姩鍒ゆ柇鏄?input 杩樻槸 output
    if inp is not None and out is None:
        # 鍙湁 input锛宱utput_data 涓?None
        pass
    elif inp is None and out is not None:
        # 鍙湁 output锛屽悓鏃跺綋浣?input 浣跨敤
        inp = out
    elif inp is not None and out is not None:
        # 涓や釜閮芥湁锛岃嚜鍔ㄦ娴嬫槸鍚﹀弽浜?
        out_has_risk = any("risk_normalized" in g for g in out.get("grids", [])[:10])
        inp_has_risk = any("risk_normalized" in g for g in inp.get("grids", [])[:10])
        if not out_has_risk and inp_has_risk:
            print(f"  [auto-fix] 妫€娴嬪埌鍙傛暟椤哄簭棰犲€掞細浜ゆ崲 output/input")
            out, inp = inp, out

    if inp is None:
        raise ValueError("鑷冲皯闇€瑕佹彁渚?input_path 鎴?output_path 涔嬩竴")

    # hex_size: 浼樺厛浠?input 鍙?
    hex_size = 1.0
    for g in inp["grids"]:
        if g.get("hex_size"):
            hex_size = float(g["hex_size"])
            break

    # grid_map 鍩轰簬 input_data
    grid_map = {g["grid_id"]: g for g in inp["grids"]}

    # species_map 浠?input_data 鍙?
    species_map = {}
    for g in inp.get("grids", []):
        if "species_densities" in g:
            species_map[g["grid_id"]] = g["species_densities"]

    # 濡傛灉 output 涔熸湁 species_densities 浣?input 娌℃湁锛屼粠 output 琛ュ厖
    if not species_map and out:
        for g in out.get("grids", []):
            if "species_densities" in g:
                species_map[g["grid_id"]] = g["species_densities"]

    # boundary_xy: 浼樺厛浠?input 鍙?
    boundary_xy = None
    for src in [inp, out]:
        if src and "map_config" in src:
            bl = src["map_config"].get("boundary_locations")
            if bl:
                boundary_xy = []
                for item in bl:
                    if isinstance(item, dict):
                        boundary_xy.append((item['x'], item['y']))
                    else:
                        boundary_xy.append(tuple(item))
                break

    return inp, out, grid_map, species_map, hex_size, boundary_xy


# ---------------------------------------------------------------------------
# 甯冨眬杈呭姪锛氬湴鍥?ax 璁剧疆 + 鍙充晶鍥句緥 ax
# ---------------------------------------------------------------------------

def compute_figsize(grids, hex_size, grid_dpi=80, save_dpi=150, has_colorbar=False):
    """
    鏍规嵁 grid_dpi锛堟瘡涓綉鏍煎湪杈撳嚭鍥剧墖涓殑鍍忕礌鏁帮級鍔ㄦ€佽绠?figsize銆?

    grid_dpi: 姣忎釜鍏竟褰㈢綉鏍煎湪鏈€缁堝浘鐗囦腑鍗犵敤鐨勫儚绱犲搴︼紙鐩村緞鏂瑰悜锛?
    save_dpi: matplotlib savefig 鐨?DPI
    杩斿洖: (fig_width_inches, fig_height_inches)
    """
    if not grids:
        return (14, 9)
    # 鍙窡韪?min/max锛岄伩鍏嶅垎閰嶅叏閲忓垪琛?
    x_min = x_max = y_min = y_max = None
    for g in grids:
        cx, cy = grid_center(g["q"], g["r"], hex_size)
        if x_min is None:
            x_min = x_max = cx
            y_min = y_max = cy
        else:
            if cx < x_min: x_min = cx
            if cx > x_max: x_max = cx
            if cy < y_min: y_min = cy
            if cy > y_max: y_max = cy
    margin = hex_size * 2
    data_width = x_max - x_min + hex_size * 2 + margin * 2
    data_height = y_max - y_min + hex_size * 2 + margin * 2
    hex_pixel_span = hex_size * math.sqrt(3)
    if hex_pixel_span == 0:
        hex_pixel_span = 1.0
    scale = grid_dpi / hex_pixel_span
    map_pixel_w = data_width * scale
    map_pixel_h = data_height * scale
    # Keep legend/colorbar readable even when grid_dpi is small (e.g. large maps).
    legend_pixel_w = max(grid_dpi * 6.5, 280)
    cbar_pixel_w = max(grid_dpi * 0.9, 34) if has_colorbar else 0
    total_pixel_w = map_pixel_w + cbar_pixel_w + legend_pixel_w
    total_pixel_h = max(map_pixel_h, grid_dpi * 6)
    # 闄愬埗鏈€澶у儚绱犲昂瀵革紝闃叉 OOM锛坢atplotlib 澶у浘鏋佽€楀唴瀛橈級
    MAX_PIXEL = 12000
    if total_pixel_w > MAX_PIXEL or total_pixel_h > MAX_PIXEL:
        # 绛夋瘮缂╂斁鍒?MAX_PIXEL 浠ュ唴
        s = MAX_PIXEL / max(total_pixel_w, total_pixel_h)
        total_pixel_w *= s
        total_pixel_h *= s
        map_pixel_w *= s
        map_pixel_h *= s
        legend_pixel_w *= s
        cbar_pixel_w *= s
    fig_w = total_pixel_w / save_dpi
    fig_h = total_pixel_h / save_dpi
    map_frac_w = map_pixel_w / total_pixel_w
    map_frac_h = map_pixel_h / total_pixel_h
    cbar_frac_w = cbar_pixel_w / total_pixel_w
    legend_frac_w = legend_pixel_w / total_pixel_w
    return (fig_w, fig_h), (map_frac_w, map_frac_h, cbar_frac_w, legend_frac_w)


def make_figure(grids=None, hex_size=1.0, grid_dpi=80, save_dpi=150, has_colorbar=False):
    """
    杩斿洖 (fig, ax_map, ax_cbar_or_None, ax_legend)
    has_colorbar=True  鈫?涓夊垪锛氬湴鍥?| 棰滆壊鏉?| 鍥句緥
    has_colorbar=False 鈫?涓ゅ垪锛氬湴鍥?| 鍥句緥
    """
    if grids is not None and len(grids) > 0:
        figsize, fracs = compute_figsize(grids, hex_size, grid_dpi, save_dpi, has_colorbar)
        map_fw, map_fh, cbar_fw, legend_fw = fracs
        fig = plt.figure(figsize=figsize)
        left_pad = 0.02
        right_pad = 0.01
        top_pad = 0.08
        bottom_pad = 0.06
        usable_w = 1.0 - left_pad - right_pad
        usable_h = 1.0 - top_pad - bottom_pad
        if has_colorbar:
            map_w = map_fw * usable_w
            cbar_w = cbar_fw * usable_w
            leg_w = legend_fw * usable_w
            cbar_left = left_pad
            ax_cbar = fig.add_axes([cbar_left, bottom_pad + 0.06, cbar_w, (map_fh - 0.12) * usable_h])
            map_left = cbar_left + cbar_w + 0.010
            ax_map = fig.add_axes([map_left, bottom_pad, map_w, map_fh * usable_h])
            leg_left = min(map_left + map_w + 0.014, 1.0 - right_pad - leg_w)
            ax_leg = fig.add_axes([leg_left, bottom_pad, leg_w, usable_h])
        else:
            map_w = map_fw * usable_w
            leg_w = legend_fw * usable_w
            ax_map = fig.add_axes([left_pad, bottom_pad, map_w, map_fh * usable_h])
            leg_left = min(left_pad + map_w + 0.012, 1.0 - right_pad - leg_w)
            ax_leg = fig.add_axes([leg_left, bottom_pad, leg_w, usable_h])
            ax_cbar = None
    else:
        fig = plt.figure(figsize=(14, 9))
        if has_colorbar:
            ax_cbar = fig.add_axes([0.02, 0.12, 0.025, 0.62])
            ax_map  = fig.add_axes([0.06, 0.06, 0.67, 0.86])
            ax_leg  = fig.add_axes([0.76, 0.06, 0.22, 0.86])
        else:
            ax_map  = fig.add_axes([0.02, 0.06, 0.76, 0.86])
            ax_cbar = None
            ax_leg  = fig.add_axes([0.80, 0.06, 0.18, 0.86])
    style_figure(fig)
    style_map_ax(ax_map)
    style_panel_ax(ax_leg)
    if ax_cbar is not None:
        ax_cbar.set_facecolor(PANEL_BG_COLOR)
        for spine in ax_cbar.spines.values():
            spine.set_color(PANEL_EDGE_COLOR)
            spine.set_linewidth(0.8)
    return fig, ax_map, ax_cbar, ax_leg


def setup_map_ax(ax, grids, hex_size, margin=1.5):
    x_min = x_max = y_min = y_max = None
    for g in grids:
        cx, cy = grid_center(g["q"], g["r"], hex_size)
        if x_min is None:
            x_min = x_max = cx
            y_min = y_max = cy
        else:
            if cx < x_min: x_min = cx
            if cx > x_max: x_max = cx
            if cy < y_min: y_min = cy
            if cy > y_max: y_max = cy
    ax.set_xlim(x_min - hex_size - margin, x_max + hex_size + margin)
    ax.set_ylim(y_min - hex_size - margin, y_max + hex_size + margin)
    ax.set_aspect('equal')


def draw_boundary(ax, grids, boundary_xy, hex_size):
    """
    鍦ㄨ竟鐣屾牸瀛愮殑澶栦晶杈逛笂鐢讳繚鎶ゅ尯杞粨绾裤€?
    boundary_xy: [(x, y), ...] 杈圭晫鏍煎瓙鐨勭瑳鍗″皵鍧愭爣锛堟潵鑷?input JSON锛?
    閫氳繃 x/y 鍖归厤 grids 閲岀殑鏍煎瓙锛屾壘鍒板搴旂殑 q/r锛屽啀鎵惧嚭鏈濆悜淇濇姢鍖哄鐨勫叚杈瑰舰杈圭粯鍒躲€?
    """
    if not boundary_xy:
        return

    # 寤虹珛 (x, y) 鈫?grid 鐨勬槧灏?
    xy_to_grid = {(g["x"], g["y"]): g for g in grids}
    # 淇濇姢鍖哄唴鎵€鏈夋牸瀛愮殑 (q, r) 闆嗗悎
    inner_qr = {(g["q"], g["r"]) for g in grids}

    # pointy-top 鍏竟褰㈢殑 6 涓偦灞呮柟鍚戯紙axial 鍧愭爣鍋忕Щ锛?
    # 瀵瑰簲杈圭殑涓や釜椤剁偣瑙掑害绱㈠紩锛堥《鐐逛粠 -30掳 寮€濮嬶紝姣?60掳 涓€涓級
    # 鏂瑰悜椤哄簭锛欵, NE, NW, W, SW, SE
    neighbor_dirs = [(1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1)]
    # 姣忎釜鏂瑰悜瀵瑰簲鐨勫渚ц竟椤剁偣绱㈠紩锛坧ointy-top锛岄《鐐?i 鍦ㄨ搴?60*i - 30 搴︼級
    # FIX: Rotate direction mapping to match actual deployment
    dir_to_edge_verts = {
        (1,  0): (1, 0),   # E  鈫?椤剁偣 1,0
        (0,  1): (2, 1),   # NE 鈫?椤剁偣 2,1
        (-1, 1): (3, 2),   # NW 鈫?椤剁偣 3,2
        (-1, 0): (4, 3),   # W  鈫?椤剁偣 4,3
        (0, -1): (5, 4),   # SW 鈫?椤剁偣 5,4
        (1, -1): (0, 5),   # SE 鈫?椤剁偣 0,5
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
        for (dq, dr), (vi, vj) in dir_to_edge_verts.items():
            nq, nr = q + dq, r + dr
            if (nq, nr) not in inner_qr:
                # 杩欐潯杈规湞鍚戜繚鎶ゅ尯澶栵紝鐢昏疆寤撶嚎
                p1 = get_corner(cx, cy, hex_size, vi)
                p2 = get_corner(cx, cy, hex_size, vj)
                ax.plot([p1[0], p2[0]], [p1[1], p2[1]],
                        color=BOUNDARY_COLOR, lw=BOUNDARY_LINEWIDTH, zorder=6, solid_capstyle="round")


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
    # O(1) (q, r) 鈫?grid_id 鏌ヨ锛岄伩鍏?O(N虏) 鎵弿
    qr_to_grid_id = {(g["q"], g["r"]): g["grid_id"] for g in grids}

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
                
                # Check if this neighbor exists in our grid set (O(1) lookup)
                neighbor_id = qr_to_grid_id.get((neighbor_q, neighbor_r))
                
                if neighbor_id is None:
                    # This is a boundary direction - draw the edge
                    vi, vj = dir_to_corners[dir_idx]
                    p1 = get_corner(cx1, cy1, hex_size, vi)
                    p2 = get_corner(cx1, cy1, hex_size, vj)
                    ax.plot([p1[0], p2[0]], [p1[1], p2[1]],
                            color=color, lw=FENCE_EDGE_LINEWIDTH, zorder=7,
                            solid_capstyle="round")
                    boundary_edge_count += 1
    
    # Debug output (disabled)
    # if fence_edges:
    #     print(f"[DEBUG] Fence edge visualization:")
    #     print(f"  - Total fence edges in data: {len(fence_edges)}")
    #     print(f"  - Boundary edges drawn: {boundary_edge_count}")
    #     print(f"  - Internal edges skipped: {internal_edge_skipped}")
# Legend and colorbar helpers
def legend_in_ax(ax_leg, handles, title, y_start=1.0, fontsize=9, title_fontsize=9):
    """Draw a compact legend section and return next y position."""
    n_items = max(1, len(handles))
    title_gap = 0.040
    default_item_gap = 0.036
    min_item_gap = 0.024
    available = max(0.10, y_start - 0.02)
    item_gap_cap = (available - title_gap - 0.012) / n_items
    item_gap = max(min_item_gap, min(default_item_gap, item_gap_cap))
    bottom_gap = max(0.010, item_gap * 0.22)
    marker_y = -0.002
    text_x = 0.195

    ax_leg.text(
        0.05,
        y_start,
        title,
        transform=ax_leg.transAxes,
        fontsize=title_fontsize,
        fontweight="bold",
        va="top",
        color=TEXT_COLOR,
    )
    y = y_start - title_gap
    for h in handles:
        if isinstance(h, mpatches.Patch):
            box_h = min(0.020, item_gap * 0.62)
            box_w = 0.10
            rect = mpatches.Rectangle(
                (0.05, y - box_h * 0.52),
                box_w,
                box_h,
                facecolor=h.get_facecolor(),
                edgecolor=PANEL_EDGE_COLOR,
                linewidth=0.7,
                transform=ax_leg.transAxes,
                clip_on=False,
            )
            ax_leg.add_patch(rect)
        else:
            marker = h.get_marker()
            mfc = h.get_markerfacecolor()
            mec = h.get_markeredgecolor()
            line_color = h.get_color() if h.get_color() not in (None, "w") else PANEL_EDGE_COLOR
            marker_size = max(6.8, h.get_markersize())
            linestyle = h.get_linestyle()
            draw_line = str(linestyle).lower() not in ("none", "", " ")
            marker_x = 0.11
            if draw_line:
                ax_leg.plot(
                    [0.05, 0.17],
                    [y + marker_y, y + marker_y],
                    color=line_color,
                    linewidth=max(1.4, h.get_linewidth()),
                    transform=ax_leg.transAxes,
                    clip_on=False,
                )
            else:
                marker_x = 0.095
            ax_leg.plot(
                marker_x,
                y + marker_y,
                marker=marker,
                color="w",
                markerfacecolor=mfc,
                markeredgecolor=mec,
                markersize=marker_size,
                transform=ax_leg.transAxes,
                clip_on=False,
            )
        ax_leg.text(
            text_x,
            y + marker_y,
            h.get_label(),
            transform=ax_leg.transAxes,
            fontsize=fontsize,
            va="center",
            color=SUBTLE_TEXT_COLOR,
        )
        y -= item_gap
    return y - bottom_gap


def add_colorbar(fig, ax_cbar, cmap, norm, label=None, show_text=True):
    """Draw colorbar in dedicated axis with optional label/ticks."""
    sm = cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cb = fig.colorbar(sm, cax=ax_cbar)
    if show_text:
        if label:
            cb.set_label(label, fontsize=8, color=TEXT_COLOR, labelpad=3)
        cb.ax.tick_params(labelsize=7, colors=SUBTLE_TEXT_COLOR, pad=1)
    else:
        cb.set_label("")
        cb.set_ticks([])
        cb.ax.tick_params(left=False, right=False, labelleft=False, labelright=False)
    cb.outline.set_edgecolor(PANEL_EDGE_COLOR)
    cb.outline.set_linewidth(0.8)


# ---------------------------------------------------------------------------
# 甯搁噺
# ---------------------------------------------------------------------------

TERRAIN_COLORS = {
    "SparseGrass": "#d9edc7",
    "DenseGrass":  "#4f8a3d",
    "WaterHole":   "#5f9fd6",
    "SaltMarsh":   "#d8c98a",
    "Road":        "#7a8089",
}

RESOURCE_MARKERS = {
    "camera":         ("s", "#3f7fbf", "Camera"),
    "drone":          ("^", "#d87a35", "Drone"),
    "camp":           ("D", "#7661a8", "Camp"),
    "patrol_rangers": ("o", "#3f9d5d", "Patrol"),
}

FENCE_COLOR = "#b03a2e"
FENCE_EDGE_LINEWIDTH = 3.0  # Thicker for better visibility

SPECIES_STYLE = {
    "rhino":    {"marker": "^", "color": "#8a5a2b", "size_scale": 120, "fill_color": "#8a5a2b"},
    "elephant": {"marker": "s", "color": "#5e7288", "size_scale": 120, "fill_color": "#5e7288"},
    "bird":     {"marker": "o", "color": "#d95f4c", "size_scale": 80,  "fill_color": "#d95f4c"},
}


def _edge_grid_ids(grids, boundary_xy=None):
    """
    杩斿洖杈圭紭缃戞牸鐨処D闆嗗悎
    
    濡傛灉鎻愪緵浜哹oundary_xy锛屼娇鐢ㄥ疄闄呯殑杈圭晫缃戞牸
    鍚﹀垯浣跨敤鐭╁舰杈圭晫鐨勮竟缂樼綉鏍硷紙鍚戝悗鍏煎锛?
    """
    if boundary_xy:
        # 浣跨敤瀹為檯鐨勮竟鐣岀綉鏍?
        xy_to_grid = {(g["x"], g["y"]): g for g in grids}
        return {xy_to_grid[(x, y)]["grid_id"] for (x, y) in boundary_xy if (x, y) in xy_to_grid}
    else:
        # 浣跨敤鐭╁舰杈圭晫鐨勮竟缂樼綉鏍硷紙鏃ч€昏緫锛?
        rows = [g["r"] for g in grids]
        cols = [g["q"] + g["r"] // 2 for g in grids]
        min_r, max_r = min(rows), max(rows)
        min_c, max_c = min(cols), max(cols)
        return {g["grid_id"] for g in grids
                if g["r"] in (min_r, max_r) or (g["q"] + g["r"] // 2) in (min_c, max_c)}


def _draw_resources(ax, grids, out, hex_size, edge_ids):
    """鍦?ax 涓婄粯鍒舵墍鏈夎祫婧愬浘鏍囷紙闄や簡鍥存爮锛屽洿鏍忕敤鍔犵矖杈规樉绀猴級
    
    鍥存爮鍙湪瀹為檯閮ㄧ讲鐨勮竟涓婃樉绀猴紙鐢ㄥ姞绮楄竟锛夛紝涓嶅啀鐢ㄤ簲杈瑰舰鍦ㄧ綉鏍煎唴鏄剧ず
    """
    # NOTE: Fence deployment is now shown with bold edges in draw_deployed_fence_edges()
    # No need to draw pentagon markers inside grid cells
    
    centers = {g["grid_id"]: grid_center(g["q"], g["r"], hex_size) for g in grids}

    # 鎵归噺鎸夎祫婧愮被鍨嬫敹闆嗗潗鏍囷紝涓€娆?scatter 璋冪敤缁樺埗鎵€鏈夊悓绫诲瀷璧勬簮
    resource_coords = {key: [] for key in RESOURCE_MARKERS}
    resource_texts = []  # (x, y, text, color)

    for g in grids:
        cx, cy = centers[g["grid_id"]]
        dep = g.get("deployment", {})
        if not dep:
            continue
        offset = 0
        for key, (marker, color, _) in RESOURCE_MARKERS.items():
            val = dep.get(key, 0)
            if val > 0:
                ox = (offset - 1) * hex_size * 0.28
                resource_coords[key].append((cx + ox, cy))
                if val > 1:
                    resource_texts.append((cx + ox, cy + hex_size * 0.35, str(val), color))
                offset += 1

    for key, (marker, color, _) in RESOURCE_MARKERS.items():
        if resource_coords[key]:
            xs, ys = zip(*resource_coords[key])
            ax.scatter(xs, ys, marker=marker, s=62, color=color,
                       edgecolors="white", linewidths=0.7, alpha=0.95, zorder=5)

    for x, y, text, color in resource_texts:
        ax.text(
            x,
            y,
            text,
            ha="center",
            va="bottom",
            fontsize=6,
            color=TEXT_COLOR,
            zorder=6,
            bbox=dict(boxstyle="round,pad=0.12", facecolor="white", edgecolor=PANEL_EDGE_COLOR, alpha=0.9),
        )


# ---------------------------------------------------------------------------
# 鍥?1锛氶闄╃儹鍔涘浘
# ---------------------------------------------------------------------------

def plot_risk_heatmap(input_data, grid_map, hex_size, boundary_xy, save_path, output_data=None, grid_dpi=80, save_dpi=150, risk_mode="auto"):
    """缁樺埗椋庨櫓鐑姏鍥?

    鏁版嵁鏉ユ簮浼樺厛绾э細
      1. output_data 鐨?risk_normalized锛堢湡瀹炲綊涓€鍖栭闄╋紝鏈€浣筹級
      2. output_data 鐨?raw_risk锛堟湭褰掍竴鍖栵紝鎸?max 褰掍竴鍖栵級
      3. input_data 鐨?risk_normalized / raw_risk / fire_risk锛坒allback锛?
    """
    # 浼樺厛浠?output_data 鍙栫湡瀹為闄?
    data = output_data if (output_data and output_data.get("grids")) else input_data
    grids = data["grids"]
    if not grids:
        print(f"  [skip] {os.path.basename(save_path)}: missing required fields")
        return

    viz_cfg = input_data.get("visualization_config", {})

    if risk_mode not in ("auto", "normalized", "raw"):
        print(f"  [skip] {os.path.basename(save_path)}: invalid risk_mode={risk_mode}")
        return

    if risk_mode == "normalized":
        if "risk_normalized" not in grids[0]:
            print(f"  [skip] {os.path.basename(save_path)}: missing risk_normalized")
            return
        risk_key = "risk_normalized"
        risk_vals = [g["risk_normalized"] for g in grids]
        norm = Normalize(vmin=0, vmax=1)
        title = "Risk Heatmap"
    elif risk_mode == "raw":
        if "raw_risk" not in grids[0]:
            print(f"  [skip] {os.path.basename(save_path)}: missing raw_risk")
            return
        risk_key = "raw_risk"
        risk_vals = [g["raw_risk"] for g in grids]
        rmax = max(risk_vals)
        raw_vmax_cfg = viz_cfg.get("raw_risk_vmax")
        try:
            raw_vmax_cfg = float(raw_vmax_cfg) if raw_vmax_cfg is not None else None
        except (TypeError, ValueError):
            raw_vmax_cfg = None
        vmax_use = raw_vmax_cfg if (raw_vmax_cfg is not None and raw_vmax_cfg > 0) else (rmax if rmax > 0 else 1)
        norm = Normalize(vmin=0, vmax=vmax_use)
        title = "Risk Heatmap (raw)"
    elif "risk_normalized" in grids[0]:
        risk_key = "risk_normalized"
        risk_vals = [g["risk_normalized"] for g in grids]
        norm = Normalize(vmin=0, vmax=1)
        title = "Risk Heatmap"
    elif "raw_risk" in grids[0]:
        risk_key = "raw_risk"
        risk_vals = [g["raw_risk"] for g in grids]
        rmax = max(risk_vals)
        norm = Normalize(vmin=0, vmax=rmax if rmax > 0 else 1)
        title = "Risk Heatmap (raw)"
    elif "fire_risk" in grids[0]:
        # fire_risk 涓嶆槸缁煎悎椋庨櫓锛岀粯鍒舵椂鏄庣‘鏍囨敞
        risk_key = "fire_risk"
        risk_vals = [g["fire_risk"] for g in grids]
        rmin, rmax = min(risk_vals), max(risk_vals)
        norm = Normalize(vmin=rmin, vmax=rmax if rmax > rmin else 1)
        title = "Fire Risk Factor Heatmap\n(NOT real risk 鈥?provide output JSON for normalized risk)"
    else:
        print(f"  [skip] {os.path.basename(save_path)} 鈥?鏁版嵁缂哄皯 risk_normalized / raw_risk / fire_risk 瀛楁")
        return

    summary = input_data.get("summary", {})
    show_grid_ids = viz_cfg.get("show_grid_ids", False)
    cmap = RISK_CMAP

    fig, ax, ax_cbar, ax_leg = make_figure(grids=grids, hex_size=hex_size, grid_dpi=grid_dpi, save_dpi=save_dpi, has_colorbar=True)

    facecolors = [cmap(norm(g[risk_key])) for g in grids]
    draw_hex_batch(ax, grids, hex_size, facecolors, edgecolor=HEX_EDGE_COLOR, lw=0.24)
    if show_grid_ids:
        for g in grids:
            cx, cy = grid_center(g["q"], g["r"], hex_size)
            ax.text(cx, cy, str(g["grid_id"]), ha="center", va="center", fontsize=5.8, zorder=4, color=TEXT_COLOR)

    setup_map_ax(ax, grids, hex_size)
    draw_boundary(ax, grids, boundary_xy, hex_size)
    ax.set_title(title, fontsize=13, fontweight="bold", pad=8, color=TEXT_COLOR)

    add_colorbar(fig, ax_cbar, cmap, norm, label=None, show_text=False)

    n_grids = len(grids)
    total_risk = sum(risk_vals)
    items = [
        ("Summary",     None,                                                  True),
        ("Total Grids", str(summary.get('total_grids', n_grids)),              False),
        ("Risk Min",    f"{min(risk_vals):.4f}",                               False),
        ("Risk Max",    f"{max(risk_vals):.4f}",                               False),
        ("Risk Mean",   f"{total_risk/n_grids:.4f}" if n_grids else "N/A",    False),
        ("Total Risk",  f"{summary.get('total_risk', total_risk):.4f}",        False),
    ]
    y = 0.965
    for label, value, bold in items:
        text = label if value is None else f"{label}: {value}"
        ax_leg.text(
            0.05,
            y,
            text,
            transform=ax_leg.transAxes,
            fontsize=9,
            va="top",
            fontweight="bold" if bold else "normal",
            fontfamily="monospace",
            color=TEXT_COLOR if bold else SUBTLE_TEXT_COLOR,
        )
        y -= 0.074 if bold else 0.064

    try:
        fig.savefig(save_path, dpi=save_dpi, bbox_inches="tight")
    finally:
        plt.close(fig)
    print(f"  saved: {save_path}")


def plot_protection_heatmap(out, hex_size, boundary_xy, save_path, grid_dpi=80, save_dpi=150):
    grids = out["grids"]
    if not grids or "protection_benefit_normalized" not in grids[0]:
        print(f"  [skip] {os.path.basename(save_path)} 鈥?杈撳嚭鏁版嵁缂哄皯 protection_benefit_normalized 瀛楁")
        return
    summary = out.get("summary", {})
    show_grid_ids = out.get("visualization_config", {}).get("show_grid_ids", False)
    cmap = matplotlib.colormaps.get_cmap("Greens")

    summary_items = [
        ("Best Fitness", f"{summary.get('best_fitness', 0):.4f}"),
        ("Total PB",     f"{summary.get('total_protection_benefit', 0):.4f}"),
        ("Avg PB",       f"{summary.get('average_protection_benefit', 0):.4f}"),
    ]

    def _draw(title, value_key, vmax, path, force_vmax=None):
        vmax_use = force_vmax if force_vmax is not None else (vmax if vmax > 0 else 1)
        norm = Normalize(vmin=0, vmax=vmax_use)
        fig, ax, ax_cbar, ax_leg = make_figure(grids=grids, hex_size=hex_size, grid_dpi=grid_dpi, save_dpi=save_dpi, has_colorbar=True)

        facecolors = [cmap(norm(g.get(value_key, 0))) for g in grids]
        draw_hex_batch(ax, grids, hex_size, facecolors, edgecolor=HEX_EDGE_COLOR, lw=0.24)
        if show_grid_ids:
            for g in grids:
                cx, cy = grid_center(g["q"], g["r"], hex_size)
                ax.text(cx, cy, str(g["grid_id"]), ha="center", va="center", fontsize=5.8, zorder=4, color=TEXT_COLOR)

        setup_map_ax(ax, grids, hex_size)
        draw_boundary(ax, grids, boundary_xy, hex_size)
        ax.set_title(title, fontsize=13, fontweight="bold", pad=8, color=TEXT_COLOR)
        add_colorbar(fig, ax_cbar, cmap, norm, label=None, show_text=False)

        y = 0.965
        ax_leg.text(0.05, y, "Summary", transform=ax_leg.transAxes,
                    fontsize=9, fontweight="bold", va="top", color=TEXT_COLOR)
        y -= 0.055
        for k, v in summary_items:
            ax_leg.text(0.05, y, f"{k}: {v}", transform=ax_leg.transAxes,
                        fontsize=8.5, va="top", fontfamily="monospace", color=SUBTLE_TEXT_COLOR)
            y -= 0.045

        fig.savefig(path, dpi=save_dpi, bbox_inches="tight")
        plt.close(fig)
        print(f"  saved: {path}")

    # Normalized
    norm_max = max((g.get("protection_benefit_normalized", 0) for g in grids), default=1)
    _draw("Protection Benefit (Normalized, 0-1)", "protection_benefit_normalized",
          norm_max, save_path, force_vmax=1.0)

    # Raw 鈥?derive save path by inserting _raw before extension
    base, ext = os.path.splitext(save_path)
    raw_path = f"{base}_raw{ext}"
    raw_max = max((g.get("protection_benefit_raw", 0) for g in grids), default=1)
    _draw("Protection Benefit (Raw, absolute scale)", "protection_benefit_raw",
          raw_max, raw_path, force_vmax=1.0)


def plot_risk_comparison(out, hex_size, boundary_xy, save_path, grid_dpi=80, save_dpi=150):
    """Compare risk before deployment and residual risk after deployment."""
    grids = out["grids"]
    summary = out.get("summary", {})
    show_grid_ids = out.get("visualization_config", {}).get("show_grid_ids", False)

    if not grids or "residual_risk_normalized" not in grids[0]:
        print("  [skip] risk_comparison.png 鈥?杈撳嚭鏁版嵁缂哄皯 residual_risk_normalized 瀛楁")
        return
    if "risk_normalized" not in grids[0]:
        print("  [skip] risk_comparison.png 鈥?杈撳嚭鏁版嵁缂哄皯 risk_normalized 瀛楁")
        return

    cmap = RISK_CMAP

    risk_before = [g["risk_normalized"] for g in grids]
    risk_after  = [g["residual_risk_normalized"] for g in grids]
    norm = Normalize(vmin=0, vmax=1)

    figsize_single, _ = compute_figsize(grids, hex_size, grid_dpi, save_dpi, has_colorbar=True)
    fig_w = figsize_single[0]
    fig_h = figsize_single[1] * 2 + 0.5
    fig = plt.figure(figsize=(fig_w, fig_h))
    style_figure(fig)
    ax_cbar   = fig.add_axes([0.02, 0.08, 0.02, 0.80])
    ax_before = fig.add_axes([0.07, 0.52, 0.70, 0.46])
    ax_after  = fig.add_axes([0.07, 0.06, 0.70, 0.46])
    ax_leg    = fig.add_axes([0.80, 0.06, 0.18, 0.88])

    for ax in (ax_before, ax_after):
        style_map_ax(ax)
    style_panel_ax(ax_leg)
    ax_cbar.set_facecolor(PANEL_BG_COLOR)

    facecolors_before = [cmap(norm(g["risk_normalized"])) for g in grids]
    facecolors_after = [cmap(norm(g["residual_risk_normalized"])) for g in grids]
    draw_hex_batch(ax_before, grids, hex_size, facecolors_before, edgecolor=HEX_EDGE_COLOR, lw=0.24)
    draw_hex_batch(ax_after, grids, hex_size, facecolors_after, edgecolor=HEX_EDGE_COLOR, lw=0.24)
    if show_grid_ids:
        for g in grids:
            cx, cy = grid_center(g["q"], g["r"], hex_size)
            ax_before.text(cx, cy, str(g["grid_id"]), ha="center", va="center", fontsize=5.8, zorder=4, color=TEXT_COLOR)
            ax_after.text(cx, cy, str(g["grid_id"]), ha="center", va="center", fontsize=5.8, zorder=4, color=TEXT_COLOR)

    setup_map_ax(ax_before, grids, hex_size)
    setup_map_ax(ax_after, grids, hex_size)
    draw_boundary(ax_before, grids, boundary_xy, hex_size)
    draw_boundary(ax_after, grids, boundary_xy, hex_size)

    ax_before.set_title("Before Deployment\n(Normalized Risk)", fontsize=12, fontweight="bold", pad=8, color=TEXT_COLOR)
    ax_after.set_title("After Deployment\n(Residual Risk)", fontsize=12, fontweight="bold", pad=8, color=TEXT_COLOR)

    add_colorbar(fig, ax_cbar, cmap, norm, "Risk Level")

    n = len(grids)
    mean_before = sum(risk_before) / n
    mean_after  = sum(risk_after) / n
    reduction   = (mean_before - mean_after) / mean_before * 100 if mean_before > 0 else 0

    items = [
        ("Summary",        None,                          True),
        ("Total Grids",    str(summary.get('total_grids', n)),   False),
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
        ("Fitness",        f"{summary.get('best_fitness', 0):.4f}", False),
    ]
    y = 0.965
    for label, value, bold in items:
        text = label if value is None else f"{label}: {value}"
        ax_leg.text(0.05, y, text, transform=ax_leg.transAxes,
                    fontsize=8, va="top",
                    fontweight="bold" if bold else "normal",
                    fontfamily="monospace",
                    color=TEXT_COLOR if bold else SUBTLE_TEXT_COLOR)
        y -= 0.062 if bold else 0.054

    fig.savefig(save_path, dpi=save_dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved: {save_path}")


def plot_terrain_map(input_data, hex_size, boundary_xy, save_path, output_data=None, grid_dpi=80, save_dpi=150):
    """Plot terrain map and optionally overlay deployed fences."""
    grids = input_data["grids"]
    show_grid_ids = input_data.get("visualization_config", {}).get("show_grid_ids", False)
    fig, ax, _, ax_leg = make_figure(grids=grids, hex_size=hex_size, grid_dpi=grid_dpi, save_dpi=save_dpi, has_colorbar=False)

    facecolors = [TERRAIN_COLORS.get(g["terrain_type"], "#ccc") for g in grids]
    draw_hex_batch(ax, grids, hex_size, facecolors, edgecolor=HEX_EDGE_COLOR, lw=0.24)
    if show_grid_ids:
        for g in grids:
            cx, cy = grid_center(g["q"], g["r"], hex_size)
            ax.text(cx, cy, str(g["grid_id"]), ha="center", va="center", fontsize=5.8, zorder=4, color=TEXT_COLOR)

    if output_data:
        draw_deployed_fence_edges(ax, grids, output_data, hex_size, color=BOUNDARY_COLOR)
    setup_map_ax(ax, grids, hex_size)
    draw_boundary(ax, grids, boundary_xy, hex_size)
    ax.set_title("Terrain Map", fontsize=13, fontweight="bold", pad=8, color=TEXT_COLOR)

    handles = [mpatches.Patch(facecolor=c, edgecolor=PANEL_EDGE_COLOR, linewidth=0.6, label=t)
               for t, c in TERRAIN_COLORS.items()]
    if output_data:
        handles.append(
            plt.Line2D([0], [1], color=BOUNDARY_COLOR, linewidth=FENCE_EDGE_LINEWIDTH * 1.5,
                       label="Fence (bold edge)")
        )
    legend_in_ax(ax_leg, handles, "Terrain Type", y_start=0.97)

    fig.savefig(save_path, dpi=save_dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved: {save_path}")


def plot_terrain_deployment_map(out, hex_size, boundary_xy, save_path, grid_dpi=80, save_dpi=150):
    grids = out["grids"]
    if not grids or "deployment" not in grids[0]:
        print(f"  [skip] {os.path.basename(save_path)} 鈥?杈撳嚭鏁版嵁缂哄皯 deployment 瀛楁")
        return
    edge_ids = _edge_grid_ids(grids, boundary_xy)
    fig, ax, _, ax_leg = make_figure(grids=grids, hex_size=hex_size, grid_dpi=grid_dpi, save_dpi=save_dpi, has_colorbar=False)

    facecolors = [TERRAIN_COLORS.get(g["terrain_type"], "#ccc") for g in grids]
    draw_hex_batch(ax, grids, hex_size, facecolors, alpha=0.48, edgecolor=HEX_EDGE_COLOR, lw=0.22)

    _draw_resources(ax, grids, out, hex_size, edge_ids)
    draw_deployed_fence_edges(ax, grids, out, hex_size)
    setup_map_ax(ax, grids, hex_size)
    draw_boundary(ax, grids, boundary_xy, hex_size)
    ax.set_title("Terrain Map with Deployment", fontsize=13, fontweight="bold", pad=8, color=TEXT_COLOR)

    terrain_handles = [mpatches.Patch(facecolor=c, edgecolor=PANEL_EDGE_COLOR, linewidth=0.6, alpha=0.6, label=t)
                       for t, c in TERRAIN_COLORS.items()]
    res_handles = [
        plt.Line2D([0], [0], linestyle="None", marker=m, color=c, markerfacecolor=c,
                   markeredgecolor="white", markeredgewidth=0.6, markersize=7.2, label=l)
        for _, (m, c, l) in RESOURCE_MARKERS.items()
    ]
    res_handles.append(
        plt.Line2D([0], [1], color=FENCE_COLOR, linewidth=FENCE_EDGE_LINEWIDTH * 2, 
                   label="Fence (bold edge)")
    )

    y = legend_in_ax(ax_leg, terrain_handles, "Terrain", y_start=0.97)
    legend_in_ax(ax_leg, res_handles, "Resources", y_start=y)

    fig.savefig(save_path, dpi=save_dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved: {save_path}")


def _species_stats_text(species_map, all_species, total_grids):
    lines = []
    for sp in all_species:
        vals = [sd[sp] for sd in species_map.values() if sd.get(sp, 0) > 0]
        if not vals:
            continue
        cnt = len(vals)
        pct = 100 * cnt / total_grids
        lo, hi = min(vals), max(vals)
        avg = sum(vals) / cnt
        lines.append(f"{sp}: {cnt} grids ({pct:.1f}%), density [{lo:.2f}, {hi:.2f}], mean={avg:.2f}")
    overlap = sum(1 for sd in species_map.values()
                  if sum(1 for v in sd.values() if v > 0) > 1)
    if overlap > 0:
        lines.append(f"Multi-species hotspot grids: {overlap}")
    return "\n".join(lines)


def _draw_hex_heatmap(ax, grids, hex_size, species, species_map, cmap, norm):
    from matplotlib.patches import Polygon
    from matplotlib.collections import PatchCollection
    patches = []
    colors = []
    for g in grids:
        cx, cy = grid_center(g["q"], g["r"], hex_size)
        corners = hex_corners(cx, cy, hex_size * 0.97)
        patches.append(Polygon(corners, closed=True))
        sd = species_map.get(g["grid_id"], {})
        d = sd.get(species, 0)
        colors.append(cmap(norm(d)))
    pc = PatchCollection(patches, facecolors=colors, edgecolors=HEX_EDGE_COLOR, linewidths=0.24)
    ax.add_collection(pc)
    style_map_ax(ax)
    ax.autoscale_view()


def _draw_composite(ax, grids, hex_size, all_species, species_map):
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
        sd = species_map.get(g["grid_id"], {})
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
                             edgecolors=HEX_EDGE_COLOR, linewidths=0.24, alpha=0.55)
        ax.add_collection(pc)

    for sp in all_species:
        if not species_patches[sp]:
            continue
        patches, densities = zip(*species_patches[sp])
        fill_color = SPECIES_STYLE.get(sp, {}).get("fill_color", "#333")
        base_rgb = mcolors.to_rgb(fill_color)
        face_colors = [(*base_rgb, 0.3 + 0.6 * d) for d in densities]
        pc = PatchCollection(patches, facecolors=face_colors,
                             edgecolors=HEX_EDGE_COLOR, linewidths=0.24)
        ax.add_collection(pc)

    for cx, cy, active, corners in multi_species_grids:
        border_x = [c[0] for c in corners] + [corners[0][0]]
        border_y = [c[1] for c in corners] + [corners[0][1]]
        ax.plot(border_x, border_y, color=HEX_EDGE_COLOR, linewidth=0.24, zorder=4)
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

    style_map_ax(ax)
    ax.autoscale_view()


def plot_species_map(input_data, species_map, hex_size, boundary_xy, save_path, grid_dpi=80, save_dpi=150):
    """缁樺埗鐗╃瀵嗗害鍦板浘锛屼粎闇€ input JSON 鏁版嵁"""
    grids = input_data["grids"]
    if not species_map:
        print("  [skip] species_map.png 鈥?no species data")
        return

    all_species = sorted({sp for sd in species_map.values() for sp in sd})
    stats_text = _species_stats_text(species_map, all_species, len(grids))

    fig, ax, _, ax_leg = make_figure(grids=grids, hex_size=hex_size, grid_dpi=grid_dpi, save_dpi=save_dpi, has_colorbar=False)

    # 鎵归噺缁樺埗鍦板舰鍏竟褰?
    facecolors = [TERRAIN_COLORS.get(g["terrain_type"], "#ccc") for g in grids]
    draw_hex_batch(ax, grids, hex_size, facecolors, alpha=0.50, edgecolor=HEX_EDGE_COLOR, lw=0.22)

    # 鎵归噺缁樺埗鐗╃鏍囪锛堟瘡涓墿绉嶄竴娆?scatter 璋冪敤锛?
    # 棰勮绠楁瘡涓綉鏍肩殑娲昏穬鐗╃鍒楄〃锛岄伩鍏嶅唴灞傚惊鐜噸澶嶈绠?
    grid_active = {}
    for g in grids:
        sd = species_map.get(g["grid_id"], {})
        grid_active[g["grid_id"]] = [s for s in all_species if sd.get(s, 0) > 0]

    for sp in all_species:
        style = SPECIES_STYLE.get(sp, {"marker": "P", "color": "#333", "size_scale": 80})
        xs, ys, sizes = [], [], []
        for g in grids:
            sd = species_map.get(g["grid_id"], {})
            d = sd.get(sp, 0)
            if d <= 0:
                continue
            cx, cy = grid_center(g["q"], g["r"], hex_size)
            active = grid_active[g["grid_id"]]
            i = active.index(sp)
            n = len(active)
            ox = (i - (n - 1) / 2) * hex_size * 0.35
            xs.append(cx + ox)
            ys.append(cy)
            sizes.append(max(10, style["size_scale"] * d))
        if xs:
            ax.scatter(xs, ys, marker=style["marker"], s=sizes,
                       color=style["color"], edgecolors="white",
                       linewidths=0.6, alpha=0.9, zorder=4)

    setup_map_ax(ax, grids, hex_size)
    draw_boundary(ax, grids, boundary_xy, hex_size)
    ax.set_title("Species Density Map", fontsize=13, fontweight="bold", pad=8, color=TEXT_COLOR)

    terrain_handles = [mpatches.Patch(facecolor=c, edgecolor=PANEL_EDGE_COLOR, linewidth=0.6, alpha=0.55, label=t)
                       for t, c in TERRAIN_COLORS.items()]
    species_handles = [
        plt.Line2D([0], [0], marker=SPECIES_STYLE.get(sp, {}).get("marker", "P"),
                   color="w",
                   markerfacecolor=SPECIES_STYLE.get(sp, {}).get("color", "#333"),
                   markeredgecolor="white", markersize=9,
                   label=f"{sp} (size ~ density)")
        for sp in all_species
    ]

    y = legend_in_ax(ax_leg, terrain_handles, "Terrain", y_start=0.97)
    legend_in_ax(ax_leg, species_handles, "Species Density", y_start=y)

    fig.text(0.02, 0.01, stats_text, fontsize=9, fontfamily="monospace", color=SUBTLE_TEXT_COLOR,
             verticalalignment="bottom",
             bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor=PANEL_EDGE_COLOR, alpha=0.95))

    fig.savefig(save_path, dpi=save_dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved: {save_path}")


def _compute_panel_figsize(grids, hex_size, grid_dpi, save_dpi):
    x_min = x_max = y_min = y_max = None
    for g in grids:
        cx, cy = grid_center(g["q"], g["r"], hex_size)
        if x_min is None:
            x_min = x_max = cx
            y_min = y_max = cy
        else:
            if cx < x_min: x_min = cx
            if cx > x_max: x_max = cx
            if cy < y_min: y_min = cy
            if cy > y_max: y_max = cy
    margin = hex_size * 2
    data_width = x_max - x_min + hex_size * 2 + margin * 2
    data_height = y_max - y_min + hex_size * 2 + margin * 2
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


def plot_species_panels(out, species_map, hex_size, boundary_xy, save_path, grid_dpi=80, save_dpi=150):
    import matplotlib.colors as mcolors
    from matplotlib.cm import ScalarMappable

    grids = out["grids"]
    if not species_map:
        return

    all_species = sorted({sp for sd in species_map.values() for sp in sd})
    stats_text = _species_stats_text(species_map, all_species, len(grids))
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
        _draw_hex_heatmap(ax, grids, hex_size, sp, species_map, cmap, norm)

        cbar_left = left + panel_w * 0.88 + 0.005
        cbar_bottom = bottom + panel_h * 0.15
        cbar_h = panel_h * 0.7 - title_h
        ax_cbar = fig.add_axes([cbar_left, cbar_bottom, panel_w * 0.04, cbar_h])
        sm = ScalarMappable(cmap=cmap, norm=norm)
        sm.set_array([])
        cbar = fig.colorbar(sm, cax=ax_cbar)
        cbar.set_label("Density", fontsize=8, color=TEXT_COLOR)
        cbar.ax.tick_params(labelsize=7, colors=SUBTLE_TEXT_COLOR)

        fig.text(left + panel_w * 0.44, bottom + panel_h - title_h * 0.3,
                 f"{sp.capitalize()} Density", fontsize=11, fontweight="bold", color=TEXT_COLOR,
                 ha="center", va="bottom")

    comp_idx = n_species
    comp_row = comp_idx // ncols
    comp_col = comp_idx % ncols
    comp_left = comp_col * (panel_w + gap_frac_w)
    comp_bottom = (nrows - 1 - comp_row) * (panel_h + gap_frac_h) + 0.06

    ax_comp = fig.add_axes([comp_left, comp_bottom, panel_w, panel_h - title_h])
    _draw_composite(ax_comp, grids, hex_size, all_species, species_map)
    fig.text(comp_left + panel_w * 0.5, comp_bottom + panel_h - title_h * 0.3,
             "Composite Overview", fontsize=11, fontweight="bold", color=TEXT_COLOR, ha="center", va="bottom")

    legend_items = []
    for sp in all_species:
        fill_color = SPECIES_STYLE.get(sp, {}).get("fill_color", "#333")
        legend_items.append(mpatches.Patch(facecolor=fill_color, edgecolor=PANEL_EDGE_COLOR,
                                           linewidth=0.5, alpha=0.7, label=sp))
    terrain_items = [mpatches.Patch(facecolor=c, edgecolor=PANEL_EDGE_COLOR, linewidth=0.6, alpha=0.55, label=t)
                     for t, c in TERRAIN_COLORS.items()]
    ax_comp.legend(handles=terrain_items + legend_items, loc="upper right", fontsize=7, framealpha=0.95)

    fig.text(0.02, 0.01, stats_text, fontsize=9, fontfamily="monospace", color=SUBTLE_TEXT_COLOR,
             verticalalignment="bottom",
             bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor=PANEL_EDGE_COLOR, alpha=0.95))

    fig.suptitle("Species Density Panels", fontsize=14, fontweight="bold", y=0.99, color=TEXT_COLOR)
    fig.savefig(save_path, dpi=save_dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved: {save_path}")


def plot_species_deployment_comparison(out, species_map, hex_size, boundary_xy, save_path, grid_dpi=80, save_dpi=150):
    """Compare species density (top) with deployment map (bottom)."""
    grids = out["grids"]
    if not grids or "deployment" not in grids[0]:
        print(f"  [skip] {os.path.basename(save_path)} 鈥?杈撳嚭鏁版嵁缂哄皯 deployment 瀛楁")
        return

    figsize_single, _ = compute_figsize(grids, hex_size, grid_dpi, save_dpi, has_colorbar=False)
    fig_w = figsize_single[0]
    fig_h = figsize_single[1] * 2 + 0.5
    fig = plt.figure(figsize=(fig_w, fig_h))
    
    # 涓婂崐閮ㄥ垎锛氱墿绉嶅瘑搴?
    ax1 = fig.add_axes([0.05, 0.52, 0.7, 0.46])
    
    # 涓嬪崐閮ㄥ垎锛氶儴缃茶祫婧?
    ax2 = fig.add_axes([0.05, 0.06, 0.7, 0.46])
    
    # 鍙充晶鍥句緥
    ax_leg1 = fig.add_axes([0.78, 0.06, 0.2, 0.88])
    style_panel_ax(ax_leg1)

    # ================= 涓婂崐閮ㄥ垎锛氱墿绉嶅瘑搴﹀浘
    all_species = []
    if species_map:
        all_species = sorted({sp for sd in species_map.values() for sp in sd})

    # 鎵归噺缁樺埗鍦板舰鍏竟褰?
    facecolors1 = [TERRAIN_COLORS.get(g["terrain_type"], "#ccc") for g in grids]
    draw_hex_batch(ax1, grids, hex_size, facecolors1, alpha=0.5, edgecolor=HEX_EDGE_COLOR, lw=0.22)

    # 鎵归噺缁樺埗鐗╃鏍囪
    if species_map:
        # 棰勮绠楁瘡涓綉鏍肩殑娲昏穬鐗╃鍒楄〃
        grid_active = {}
        for g in grids:
            sd = species_map.get(g["grid_id"], {})
            grid_active[g["grid_id"]] = [s for s in all_species if sd.get(s, 0) > 0]

        for sp in all_species:
            style = SPECIES_STYLE.get(sp, {"marker": "P", "color": "#333", "size_scale": 80})
            xs, ys, sizes = [], [], []
            for g in grids:
                sd = species_map.get(g["grid_id"], {})
                d = sd.get(sp, 0)
                if d <= 0:
                    continue
                cx, cy = grid_center(g["q"], g["r"], hex_size)
                active = grid_active[g["grid_id"]]
                i = active.index(sp)
                n = len(active)
                ox = (i - (n - 1) / 2) * hex_size * 0.35
                xs.append(cx + ox)
                ys.append(cy)
                sizes.append(max(10, style["size_scale"] * d))
            if xs:
                ax1.scatter(xs, ys, marker=style["marker"], s=sizes,
                           color=style["color"], edgecolors="white",
                           linewidths=0.6, alpha=0.9, zorder=4)

    setup_map_ax(ax1, grids, hex_size)
    draw_boundary(ax1, grids, boundary_xy, hex_size)
    ax1.set_title("Species Density (Top)", fontsize=13, fontweight="bold", pad=8, color=TEXT_COLOR)

    # ================= 涓嬪崐閮ㄥ垎锛氶儴缃茶祫婧愬浘
    facecolors2 = [TERRAIN_COLORS.get(g["terrain_type"], "#ccc") for g in grids]
    draw_hex_batch(ax2, grids, hex_size, facecolors2, alpha=0.5, edgecolor=HEX_EDGE_COLOR, lw=0.22)

    _draw_resources(ax2, grids, out, hex_size, edge_ids=_edge_grid_ids(grids, boundary_xy))
    draw_deployed_fence_edges(ax2, grids, out, hex_size)
    
    setup_map_ax(ax2, grids, hex_size)
    draw_boundary(ax2, grids, boundary_xy, hex_size)
    ax2.set_title("Deployment (Bottom)", fontsize=13, fontweight="bold", pad=8, color=TEXT_COLOR)

    # ================= 鍙充晶鍥句緥
    terrain_handles = [mpatches.Patch(facecolor=c, edgecolor=PANEL_EDGE_COLOR, linewidth=0.6, alpha=0.55, label=t)
                       for t, c in TERRAIN_COLORS.items()]
    res_handles = [
        plt.Line2D([0], [0], linestyle="None", marker=m, color=c, markerfacecolor=c,
                   markeredgecolor="white", markeredgewidth=0.6, markersize=7.2, label=l)
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
                       markeredgecolor="white", markersize=9,
                       label=f"{sp} (size ~ density)")
            for sp in all_species
        ]
        legend_in_ax(ax_leg1, species_handles, "Species Density", y_start=y)

    fig.savefig(save_path, dpi=save_dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved: {save_path}")


def plot_protection_deployment_comparison(out, hex_size, boundary_xy, save_path, grid_dpi=80, save_dpi=150):
    """Compare protection benefit heatmap (top) with deployment map (bottom)."""
    grids = out["grids"]
    if not grids or "protection_benefit_normalized" not in grids[0] or "deployment" not in grids[0]:
        print(f"  [skip] {os.path.basename(save_path)} 鈥?杈撳嚭鏁版嵁缂哄皯淇濇姢鏀剁泭/閮ㄧ讲瀛楁")
        return
    summary = out.get("summary", {})
    show_grid_ids = out.get("visualization_config", {}).get("show_grid_ids", False)
    edge_ids = _edge_grid_ids(grids, boundary_xy)

    figsize_single, _ = compute_figsize(grids, hex_size, grid_dpi, save_dpi, has_colorbar=True)
    fig_w = figsize_single[0]
    fig_h = figsize_single[1] * 2 + 0.5
    fig = plt.figure(figsize=(fig_w, fig_h))
    
    # 涓婂崐閮ㄥ垎锛歅rotection Heatmap
    ax1 = fig.add_axes([0.07, 0.52, 0.65, 0.46])
    
    # 涓婂崐閮ㄥ垎棰滆壊鏉★細Protection Heatmap鍙充晶
    ax_cbar = fig.add_axes([0.74, 0.57, 0.02, 0.36])
    
    # 涓嬪崐閮ㄥ垎锛欴eployment Map
    ax2 = fig.add_axes([0.07, 0.06, 0.65, 0.46])
    
    # 鍙充晶鍥句緥
    ax_leg = fig.add_axes([0.80, 0.06, 0.18, 0.88])
    style_panel_ax(ax_leg)
    ax_cbar.set_facecolor(PANEL_BG_COLOR)

    # ================= 涓婂崐閮ㄥ垎锛歅rotection Heatmap
    cmap = matplotlib.colormaps.get_cmap("Greens")
    norm = Normalize(vmin=0, vmax=1)

    facecolors_pb = [cmap(norm(g.get("protection_benefit_normalized", 0))) for g in grids]
    draw_hex_batch(ax1, grids, hex_size, facecolors_pb, edgecolor=HEX_EDGE_COLOR, lw=0.24)
    if show_grid_ids:
        for g in grids:
            cx, cy = grid_center(g["q"], g["r"], hex_size)
            ax1.text(cx, cy, str(g["grid_id"]), ha="center", va="center", fontsize=5.8, zorder=4, color=TEXT_COLOR)

    setup_map_ax(ax1, grids, hex_size)
    draw_boundary(ax1, grids, boundary_xy, hex_size)
    ax1.set_title("Protection Benefit (Top)", fontsize=13, fontweight="bold", pad=8, color=TEXT_COLOR)

    # ================= 涓婂崐閮ㄥ垎棰滆壊鏉?
    add_colorbar(fig, ax_cbar, cmap, norm, "Protection Benefit (Normalized)")

    # ================= 涓嬪崐閮ㄥ垎锛欴eployment Map
    facecolors_dep = [TERRAIN_COLORS.get(g["terrain_type"], "#ccc") for g in grids]
    draw_hex_batch(ax2, grids, hex_size, facecolors_dep, alpha=0.5, edgecolor=HEX_EDGE_COLOR, lw=0.22)

    _draw_resources(ax2, grids, out, hex_size, edge_ids)
    draw_deployed_fence_edges(ax2, grids, out, hex_size)
    
    setup_map_ax(ax2, grids, hex_size)
    draw_boundary(ax2, grids, boundary_xy, hex_size)
    ax2.set_title("Deployment (Bottom)", fontsize=13, fontweight="bold", pad=8, color=TEXT_COLOR)

    # ================= 鍙充晶鍥句緥
    summary_items = [
        ("Summary",        None,                          True),
        ("Best Fitness",   f"{summary.get('best_fitness', 0):.4f}", False),
        ("Total PB",       f"{summary.get('total_protection_benefit', 0):.4f}", False),
        ("Avg PB",         f"{summary.get('average_protection_benefit', 0):.4f}", False),
        ("--- Resources ---", None,                      True),
    ]
    
    # 閮ㄧ讲璧勬簮缁熻
    for res, (marker, color, label) in RESOURCE_MARKERS.items():
        total = sum(g.get("deployment", {}).get(res, 0) for g in grids)
        if total > 0:
            summary_items.append((label, str(total), False))

    fence_total = sum(
        len(g.get("fences", {}).get("boundary_edge_list", []))
        for g in grids
    )
    if fence_total > 0:
        summary_items.append(("Fence Edges", str(fence_total), False))

    y = 0.965
    for label, value, bold in summary_items:
        text = label if value is None else f"{label}: {value}"
        ax_leg.text(0.05, y, text, transform=ax_leg.transAxes,
                    fontsize=8, va="top",
                    fontweight="bold" if bold else "normal",
                    fontfamily="monospace",
                    color=TEXT_COLOR if bold else SUBTLE_TEXT_COLOR)
        y -= 0.048 if bold else 0.039
        if y < 0.66:
            break
    
    # 鍦板舰鍥句緥
    terrain_handles = [mpatches.Patch(facecolor=c, edgecolor=PANEL_EDGE_COLOR, linewidth=0.6, alpha=0.55, label=t)
                       for t, c in TERRAIN_COLORS.items()]
    y = legend_in_ax(ax_leg, terrain_handles, "Terrain", y_start=min(y, 0.64))
    
    # 璧勬簮鍥句緥
    res_handles = [
        plt.Line2D([0], [0], linestyle="None", marker=m, color=c, markerfacecolor=c,
                   markeredgecolor="white", markeredgewidth=0.6, markersize=7.2, label=l)
        for _, (m, c, l) in RESOURCE_MARKERS.items()
    ]
    res_handles.append(
        plt.Line2D([0], [1], color=FENCE_COLOR, linewidth=FENCE_EDGE_LINEWIDTH * 2,
                   label="Fence (bold edge)")
    )
    legend_in_ax(ax_leg, res_handles, "Resources", y_start=min(y, 0.38))

    fig.savefig(save_path, dpi=save_dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved: {save_path}")


def plot_fitness_history(out, save_path, save_dpi=150):
    fitness_history = out.get("summary", {}).get("fitness_history")
    if not fitness_history:
        print("  [skip] fitness_history.png 鈥?杈撳嚭鏁版嵁缂哄皯 fitness_history 瀛楁")
        return

    iterations = list(range(1, len(fitness_history) + 1))
    best_val = max(fitness_history)
    best_iter = fitness_history.index(best_val) + 1

    fig, ax = plt.subplots(figsize=(10.5, 5.5))
    style_figure(fig)
    ax.set_facecolor(PANEL_BG_COLOR)

    rolling_best = np.maximum.accumulate(np.asarray(fitness_history, dtype=float))
    ax.plot(iterations, fitness_history, color="#4f86c6", linewidth=1.5, alpha=0.85, label="Best Fitness / Iter")
    ax.plot(iterations, rolling_best, color="#1f4e79", linewidth=2.0, alpha=0.95, label="Running Best")
    ax.scatter([best_iter], [best_val], color="#d64541", s=62, zorder=5, label=f"Peak: {best_val:.6f} @ {best_iter}")
    ax.axhline(y=best_val, color="#d64541", linewidth=0.9, linestyle="--", alpha=0.55)

    ax.set_xlabel("Iteration", fontsize=11, color=TEXT_COLOR)
    ax.set_ylabel("Best Fitness", fontsize=11, color=TEXT_COLOR)
    ax.set_title("Fitness Convergence", fontsize=13, fontweight="bold", pad=8, color=TEXT_COLOR)
    ax.legend(loc="lower right", fontsize=9, framealpha=0.95)
    ax.grid(True, axis="y", alpha=0.25, color="#8da2b8")
    ax.grid(False, axis="x")
    ax.set_xlim(1, len(fitness_history))
    ax.tick_params(colors=SUBTLE_TEXT_COLOR)
    for spine in ax.spines.values():
        spine.set_color(PANEL_EDGE_COLOR)
        spine.set_linewidth(0.9)

    summary = out.get("summary", {})
    stats_text = (
        f"Total Iterations: {len(fitness_history)}\n"
        f"Best Fitness: {best_val:.6f}\n"
        f"Best Iteration: {best_iter}\n"
        f"Initial Fitness: {fitness_history[0]:.6f}\n"
        f"Improvement: {best_val - fitness_history[0]:.6f}"
    )
    ax.text(0.02, 0.98, stats_text, transform=ax.transAxes,
            fontsize=8, va="top", fontfamily="monospace", color=SUBTLE_TEXT_COLOR,
            bbox=dict(boxstyle="round,pad=0.4", facecolor="white", alpha=0.95, edgecolor=PANEL_EDGE_COLOR))

    fig.tight_layout()
    fig.savefig(save_path, dpi=save_dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved: {save_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="Visualize protection pipeline output JSON",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("output", nargs="?", default=None, help="Output JSON path")
    p.add_argument("--input", "-i", default=None, help="Input JSON path")
    p.add_argument("--out_dir", "-d", default="./figures", help="Output figure directory")
    p.add_argument("--prefix", default="", help="Output filename prefix")
    p.add_argument("--grid_dpi", type=int, default=80, help="Approx pixels per hex in output image")
    p.add_argument("--dpi", type=int, default=150, help="matplotlib savefig DPI")
    return p.parse_args()


def main():
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    print(f"Loading data: output={args.output}, input={args.input}")
    input_data, output_data, grid_map, species_map, hex_size, boundary_xy = load_data(
        output_path=args.output, input_path=args.input)
    print(f"  grids: {len(input_data['grids'])}; hex_size: {hex_size}")
    if boundary_xy:
        print(f"  boundary grids: {len(boundary_xy)}")
    print(f"  grid_dpi: {args.grid_dpi}, save_dpi: {args.dpi}")
    print(f"  output_data: {'yes' if output_data else 'no'}")

    pre = args.prefix + "_" if args.prefix else ""
    print("Generating figures...")

    # 浠呴渶 input 鐨勫浘
    plot_risk_heatmap(input_data, grid_map, hex_size, boundary_xy,
                      save_path=os.path.join(args.out_dir, f"{pre}risk_heatmap.png"),
                      output_data=output_data,
                      risk_mode="normalized",
                      grid_dpi=args.grid_dpi, save_dpi=args.dpi)
    plot_risk_heatmap(input_data, grid_map, hex_size, boundary_xy,
                      save_path=os.path.join(args.out_dir, f"{pre}risk_heatmap_raw.png"),
                      output_data=output_data,
                      risk_mode="raw",
                      grid_dpi=args.grid_dpi, save_dpi=args.dpi)
    plot_terrain_map(input_data, hex_size, boundary_xy,
                     save_path=os.path.join(args.out_dir, f"{pre}terrain_map.png"),
                     output_data=output_data,
                     grid_dpi=args.grid_dpi, save_dpi=args.dpi)
    plot_species_map(input_data, species_map, hex_size, boundary_xy,
                     save_path=os.path.join(args.out_dir, f"{pre}species_map.png"),
                     grid_dpi=args.grid_dpi, save_dpi=args.dpi)

    # 闇€瑕?output 鐨勫浘
    if output_data:
        plot_risk_comparison(output_data, hex_size, boundary_xy,
                             save_path=os.path.join(args.out_dir, f"{pre}risk_comparison.png"),
                             grid_dpi=args.grid_dpi, save_dpi=args.dpi)
        plot_protection_heatmap(output_data, hex_size, boundary_xy,
                                save_path=os.path.join(args.out_dir, f"{pre}protection_heatmap.png"),
                                grid_dpi=args.grid_dpi, save_dpi=args.dpi)
        plot_terrain_deployment_map(output_data, hex_size, boundary_xy,
                                    save_path=os.path.join(args.out_dir, f"{pre}terrain_deployment_map.png"),
                                    grid_dpi=args.grid_dpi, save_dpi=args.dpi)
        plot_species_panels(output_data, species_map, hex_size, boundary_xy,
                            save_path=os.path.join(args.out_dir, f"{pre}species_panels.png"),
                            grid_dpi=args.grid_dpi, save_dpi=args.dpi)
        plot_species_deployment_comparison(output_data, species_map, hex_size, boundary_xy,
                                           save_path=os.path.join(args.out_dir, f"{pre}species_deployment_comparison.png"),
                                           grid_dpi=args.grid_dpi, save_dpi=args.dpi)
        plot_protection_deployment_comparison(output_data, hex_size, boundary_xy,
                                              save_path=os.path.join(args.out_dir, f"{pre}protection_deployment_comparison.png"),
                                              grid_dpi=args.grid_dpi, save_dpi=args.dpi)
        plot_fitness_history(output_data,
                             save_path=os.path.join(args.out_dir, f"{pre}fitness_history.png"),
                             save_dpi=args.dpi)
    else:
        print("  [skip] 閮ㄧ讲/淇濇姢鐩稿叧鍥?鈥?鏃?output 鏁版嵁")
    print("Done.")


if __name__ == "__main__":
    main()
