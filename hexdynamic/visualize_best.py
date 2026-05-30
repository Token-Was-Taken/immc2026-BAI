"""
visualize_best.py — 可视化单个 iteration 的最佳部署方案

用法:
    python visualize_best.py input.json best.json
    python visualize_best.py input.json best.json --out_dir ./figures
    python visualize_best.py input.json best.json --grid_dpi 60 --save_dpi 150
"""

import argparse
import json
import math
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from matplotlib.patches import Polygon


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
FENCE_EDGE_LINEWIDTH = 3.0


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


def load_best_data(best_path):
    with open(best_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_input_grids(input_path):
    with open(input_path, 'r', encoding='utf-8') as f:
        return json.load(f).get('grids', [])


def merge_best_to_grids(grids, best_data):
    cameras = {int(k): v for k, v in best_data.get('cameras', {}).items()}
    camps = {int(k): v for k, v in best_data.get('camps', {}).items()}
    drones = {int(k): v for k, v in best_data.get('drones', {}).items()}
    rangers = {int(k): v for k, v in best_data.get('rangers', {}).items()}
    fences_raw = best_data.get('fences', {})

    fences = {}
    for k, v in fences_raw.items():
        parts = k.split('-')
        if len(parts) == 2:
            fences[(int(parts[0]), int(parts[1]))] = v

    plot_grids = []
    for g in grids:
        gid = g['grid_id']
        ng = dict(g)
        ng['deployment'] = {
            'camera': cameras.get(gid, 0),
            'drone': drones.get(gid, 0),
            'camp': camps.get(gid, 0),
            'patrol_rangers': rangers.get(gid, 0),
        }
        grid_fences = [(gid, d) for (g_id, d) in fences.keys() if g_id == gid]
        if grid_fences:
            ng['fences'] = {
                'fence_count': len(grid_fences),
                'boundary_edge_list': [d for _, d in grid_fences]
            }
        plot_grids.append(ng)

    return plot_grids, cameras, camps, drones, rangers, fences


def compute_figsize(grids, hex_size, grid_dpi=80, save_dpi=150):
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
    total_pixel_w = map_pixel_w + legend_pixel_w
    total_pixel_h = max(map_pixel_h, grid_dpi * 6)
    fig_w = total_pixel_w / save_dpi
    fig_h = total_pixel_h / save_dpi
    map_frac_w = map_pixel_w / total_pixel_w
    map_frac_h = map_pixel_h / total_pixel_h
    legend_frac_w = legend_pixel_w / total_pixel_w
    return (fig_w, fig_h), (map_frac_w, map_frac_h, 0, legend_frac_w)


def draw_boundary(ax, grids, boundary_xy, hex_size):
    if not boundary_xy:
        return
    xy_to_grid = {(g["x"], g["y"]): g for g in grids}
    inner_qr = {(g["q"], g["r"]) for g in grids}
    neighbor_dirs = [(1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1)]
    dir_to_edge_verts = {
        (1,  0): (1, 0), (0,  1): (2, 1), (-1, 1): (3, 2),
        (-1, 0): (4, 3), (0, -1): (5, 4), (1, -1): (0, 5),
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
                p1 = get_corner(cx, cy, hex_size, vi)
                p2 = get_corner(cx, cy, hex_size, vj)
                ax.plot([p1[0], p2[0]], [p1[1], p2[1]],
                        color="#1a1a1a", lw=1.8, zorder=6, solid_capstyle="round")


def draw_deployed_fence_edges(ax, grids, plot_grids, hex_size):
    grid_by_id = {g["grid_id"]: g for g in grids}
    all_grid_ids = set(grid_by_id.keys())

    dir_to_corners = {
        0: (1, 0), 1: (2, 1), 2: (3, 2),
        3: (4, 3), 4: (5, 4), 5: (0, 5),
    }

    def get_corner(cx, cy, size, i):
        a = math.pi / 3 * i - math.pi / 6
        return cx + size * math.cos(a), cy + size * math.sin(a)

    drawn_edges = set()
    for g in plot_grids:
        gid = g['grid_id']
        fence_info = g.get('fences', {})
        if not fence_info:
            continue
        for dir_idx in fence_info.get('boundary_edge_list', []):
            edge_key = (gid, None, dir_idx)
            if edge_key in drawn_edges:
                continue
            drawn_edges.add(edge_key)
            cx, cy = grid_center(g["q"], g["r"], hex_size)
            vi, vj = dir_to_corners.get(dir_idx, (0, 5))
            p1 = get_corner(cx, cy, hex_size, vi)
            p2 = get_corner(cx, cy, hex_size, vj)
            ax.plot([p1[0], p2[0]], [p1[1], p2[1]],
                    color=FENCE_COLOR, lw=FENCE_EDGE_LINEWIDTH, zorder=7, solid_capstyle="round")


def draw_resources(ax, plot_grids, hex_size):
    centers = {g["grid_id"]: grid_center(g["q"], g["r"], hex_size) for g in plot_grids}
    for g in plot_grids:
        cx, cy = centers[g["grid_id"]]
        dep = g.get("deployment", {})
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


def visualize_best(input_path, best_path, out_dir, grid_dpi=None, save_dpi=150):
    os.makedirs(out_dir, exist_ok=True)

    best_data = load_best_data(best_path)
    grids = load_input_grids(input_path)

    hex_size = 1.0
    for g in grids:
        if g.get('hex_size'):
            hex_size = float(g['hex_size'])
            break

    plot_grids, cameras, camps, drones, rangers, fences = merge_best_to_grids(grids, best_data)

    if grid_dpi is None:
        max_dim = max(len(set(g["q"] for g in grids)), len(set(g["r"] for g in grids)))
        grid_dpi = min(max(20, 4000 // max(max_dim, 1)), 80)

    figsize, fracs = compute_figsize(plot_grids, hex_size, grid_dpi, save_dpi)
    map_fw, map_fh, _, legend_fw = fracs

    fig = plt.figure(figsize=figsize)
    left_pad = 0.02
    right_pad = 0.01
    top_pad = 0.08
    bottom_pad = 0.06
    usable_w = 1.0 - left_pad - right_pad
    usable_h = 1.0 - top_pad - bottom_pad

    ax_map = fig.add_axes([left_pad, bottom_pad, map_fw * usable_w, map_fh * usable_h])
    leg_left = left_pad + map_fw * usable_w + 0.01
    ax_leg = fig.add_axes([leg_left, bottom_pad, legend_fw * usable_w, usable_h])
    ax_leg.axis("off")

    # Draw terrain
    for g in plot_grids:
        cx, cy = grid_center(g["q"], g["r"], hex_size)
        terrain = g.get("terrain_type", "SparseGrass")
        color = TERRAIN_COLORS.get(terrain, "#808080")
        draw_hex(ax_map, cx, cy, hex_size * 0.97, color, "black", 0.3)

    # Draw resources
    draw_resources(ax_map, plot_grids, hex_size)

    # Draw fences
    draw_deployed_fence_edges(ax_map, plot_grids, plot_grids, hex_size)

    # Setup map
    xs = [grid_center(g["q"], g["r"], hex_size)[0] for g in plot_grids]
    ys = [grid_center(g["q"], g["r"], hex_size)[1] for g in plot_grids]
    margin = hex_size * 2
    ax_map.set_xlim(min(xs) - hex_size - margin, max(xs) + hex_size + margin)
    ax_map.set_ylim(min(ys) - hex_size - margin, max(ys) + hex_size + margin)
    ax_map.set_aspect("equal")

    # Title
    basename = os.path.basename(best_path)
    ax_map.set_title(f"Best Deployment — {basename}", fontsize=13, fontweight="bold", pad=8)

    # Legend
    y = 0.97
    ax_leg.text(0.05, y, "Resources", transform=ax_leg.transAxes,
                fontsize=10, fontweight="bold", va="top")
    y -= 0.06
    for key, (marker, color, label) in RESOURCE_MARKERS.items():
        ax_leg.plot(0.11, y - 0.005, marker=marker, color="w",
                    markerfacecolor=color, markeredgecolor="black",
                    markersize=8, transform=ax_leg.transAxes, clip_on=False)
        ax_leg.text(0.22, y - 0.005, label, transform=ax_leg.transAxes,
                    fontsize=9, va="center")
        y -= 0.055

    y -= 0.02
    ax_leg.text(0.05, y, "Fence", transform=ax_leg.transAxes,
                fontsize=10, fontweight="bold", va="top")
    y -= 0.06
    ax_leg.plot([0.05, 0.17], [y - 0.005, y - 0.005],
                color=FENCE_COLOR, linewidth=FENCE_EDGE_LINEWIDTH,
                transform=ax_leg.transAxes, clip_on=False)
    ax_leg.text(0.22, y - 0.005, "Boundary Fence", transform=ax_leg.transAxes,
                fontsize=9, va="center")

    # Stats
    stats = best_data.get('statistics', {})
    y -= 0.12
    ax_leg.text(0.05, y, "Statistics", transform=ax_leg.transAxes,
                fontsize=10, fontweight="bold", va="top")
    y -= 0.06
    for label, value in [
        ("Cameras", stats.get('total_cameras', sum(cameras.values()))),
        ("Drones", stats.get('total_drones', sum(drones.values()))),
        ("Camps", stats.get('total_camps', sum(camps.values()))),
        ("Rangers", stats.get('total_rangers', sum(rangers.values()))),
        ("Fences", stats.get('total_fence_length', sum(fences.values()))),
    ]:
        ax_leg.text(0.1, y, f"{label}: {value}", transform=ax_leg.transAxes, fontsize=9)
        y -= 0.05

    # Save
    base_name = os.path.splitext(os.path.basename(best_path))[0]
    save_path = os.path.join(out_dir, f"{base_name}_deployment.png")
    fig.savefig(save_path, dpi=save_dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {save_path}")


def main():
    parser = argparse.ArgumentParser(description="Visualize a single best.json deployment")
    parser.add_argument("input", help="Input JSON (problem definition)")
    parser.add_argument("best", help="best.json to visualize")
    parser.add_argument("--out_dir", "-d", default=".", help="Output directory")
    parser.add_argument("--grid_dpi", type=int, default=None, help="Grid DPI (auto if not set)")
    parser.add_argument("--save_dpi", type=int, default=150, help="Save DPI")
    args = parser.parse_args()

    visualize_best(args.input, args.best, args.out_dir, args.grid_dpi, args.save_dpi)


if __name__ == '__main__':
    main()
