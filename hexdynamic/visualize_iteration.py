"""
Visualize iteration results - only generates deployment-specific graphs.
Faster than full visualize_output.py (skips terrain/species/risk heatmaps that are same for all iterations).

Usage:
    python visualize_iteration.py <output_json> [--input input_json] [--out_dir output_dir]
    python visualize_iteration.py results/iteration_0000/producers_000.json --input input.json --out_dir figures/
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


def load_data(output_path, input_path=None):
    with open(output_path, "r", encoding="utf-8") as f:
        out = json.load(f)
    
    hex_size = 1.0
    for g in out.get("grids", []):
        if g.get("hex_size"):
            hex_size = float(g["hex_size"])
            break
    
    out_map = {g["grid_id"]: g for g in out["grids"]}
    return out, out_map, hex_size


def make_figure(has_colorbar=False):
    fig = plt.figure(figsize=(14, 9))
    if has_colorbar:
        ax_map = fig.add_axes([0.02, 0.06, 0.68, 0.86])
        ax_cbar = fig.add_axes([0.72, 0.12, 0.025, 0.62])
        ax_leg = fig.add_axes([0.77, 0.06, 0.21, 0.86])
    else:
        ax_map = fig.add_axes([0.02, 0.06, 0.76, 0.86])
        ax_cbar = None
        ax_leg = fig.add_axes([0.80, 0.06, 0.18, 0.86])
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


def draw_terrain_deployment_map(out, out_map, hex_size, out_dir):
    """Draw terrain + deployment overlay (only graphs that change per iteration)."""
    terrain_colors = {
        'SparseGrass': '#a8d5a2',
        'DenseGrass':  '#2d6a2d',
        'WaterHole':   '#5b9bd5',
        'SaltMarsh':   '#c8b97a',
        'Road':        '#888888',
    }
    
    fig, ax_map, _, ax_leg = make_figure(False)
    grids = [out_map[gid] for gid in sorted(out_map.keys())]
    setup_map_ax(ax_map, grids, hex_size)
    
    deployed_resources = {}
    for g in grids:
        dep = g.get('deployment', {})
        for res, cnt in dep.items():
            if cnt > 0:
                deployed_resources[g['grid_id']] = dep
    
    for g in grids:
        cx, cy = grid_center(g['q'], g['r'], hex_size)
        terrain = g.get('terrain_type', 'SparseGrass')
        color = terrain_colors.get(terrain, '#808080')
        draw_hex(ax_map, cx, cy, hex_size, color, 'black', 0.3)
    
    markers = {
        'camera': ('s', 'blue'),
        'drone': ('^', 'orange'),
        'camp': ('D', 'purple'),
        'patrol_rangers': ('o', 'green')
    }
    
    for gid, dep in deployed_resources.items():
        g = out_map[gid]
        cx, cy = grid_center(g['q'], g['r'], hex_size)
        for res, (marker, color) in markers.items():
            if dep.get(res, 0) > 0:
                ax_map.scatter([cx], [cy], marker=marker, c=color, s=80, zorder=10, edgecolors='white', lw=0.5)
    
    ax_leg.text(0.5, 0.95, "Terrain + Deployment", transform=ax_leg.transAxes,
              fontsize=14, fontweight='bold', ha='center')
    
    legend_elements = []
    for res, (marker, color) in markers.items():
        legend_elements.append(mpatches.Patch(facecolor=color, label=res))
    ax_leg.legend(handles=legend_elements, loc='upper center', bbox_to_anchor=(0.5, 0.85))
    
    summary = out.get('summary', {})
    stats = [
        f"Fitness: {summary.get('best_fitness', 0):.4f}",
        f"Total PB: {summary.get('total_protection_benefit', 0):.2f}",
        f"Cameras: {summary.get('resources_deployed', {}).get('total_cameras', 0)}",
        f"Drones: {summary.get('resources_deployed', {}).get('total_drones', 0)}",
        f"Camps: {summary.get('resources_deployed', {}).get('total_camps', 0)}",
        f"Rangers: {summary.get('resources_deployed', {}).get('total_rangers', 0)}",
    ]
    for i, text in enumerate(stats):
        ax_leg.text(0.1, 0.7 - i * 0.08, text, transform=ax_leg.transAxes, fontsize=10)
    
    fig.savefig(os.path.join(out_dir, 'terrain_deployment_map.png'), dpi=150, bbox_inches='tight')
    plt.close(fig)


def draw_risk_comparison(out, out_map, hex_size, out_dir):
    """Draw risk before vs after deployment."""
    fig = plt.figure(figsize=(14, 9))
    ax_left  = fig.add_axes([0.03, 0.06, 0.41, 0.86])
    ax_right = fig.add_axes([0.50, 0.06, 0.41, 0.86])
    ax_cbar  = fig.add_axes([0.93, 0.15, 0.02, 0.65])

    grids = [out_map[gid] for gid in sorted(out_map.keys())]
    setup_map_ax(ax_left, grids, hex_size)
    setup_map_ax(ax_right, grids, hex_size)

    risk_vals = [g.get('risk_normalized', 0) for g in grids if g.get('risk_normalized', 0) > 0]
    norm = Normalize(vmin=min(risk_vals) if risk_vals else 0, vmax=max(risk_vals) if risk_vals else 1)
    cmap = cm.YlOrRd

    for g in grids:
        cx, cy = grid_center(g['q'], g['r'], hex_size)
        draw_hex(ax_left,  cx, cy, hex_size, cmap(norm(g.get('risk_normalized', 0))),          'black', 0.3)
        draw_hex(ax_right, cx, cy, hex_size, cmap(norm(g.get('residual_risk_normalized', 0))), 'black', 0.3)

    ax_left.set_title("Before Deployment", fontsize=12)
    ax_right.set_title("After Deployment", fontsize=12)

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    plt.colorbar(sm, cax=ax_cbar)

    fig.savefig(os.path.join(out_dir, 'risk_comparison.png'), dpi=150, bbox_inches='tight')
    plt.close(fig)


def draw_protection_heatmap(out, out_map, hex_size, out_dir):
    """Draw protection benefit heatmap - both normalized and raw versions."""
    grids = [out_map[gid] for gid in sorted(out_map.keys())]
    summary = out.get('summary', {})
    stats = [
        f"Fitness: {summary.get('best_fitness', 0):.4f}",
        f"Total PB: {summary.get('total_protection_benefit', 0):.2f}",
        f"Avg PB: {summary.get('average_protection_benefit', 0):.4f}",
    ]

    def _draw(title, value_key, filename, vmin, vmax):
        fig = plt.figure(figsize=(14, 9))
        ax_map  = fig.add_axes([0.02, 0.06, 0.70, 0.86])
        ax_cbar = fig.add_axes([0.74, 0.12, 0.025, 0.62])
        ax_leg  = fig.add_axes([0.80, 0.06, 0.18, 0.86])

        setup_map_ax(ax_map, grids, hex_size)
        norm = Normalize(vmin=vmin, vmax=vmax)
        cmap = cm.Greens

        for g in grids:
            cx, cy = grid_center(g['q'], g['r'], hex_size)
            val = g.get(value_key, 0)
            draw_hex(ax_map, cx, cy, hex_size, cmap(norm(val)), 'black', 0.3)

            dep = g.get('deployment', {})
            if dep.get('camera'):
                ax_map.scatter([cx], [cy], marker='s', c='blue', s=40, zorder=10)
            if dep.get('drone'):
                ax_map.scatter([cx], [cy], marker='^', c='orange', s=40, zorder=10)
            if dep.get('camp'):
                ax_map.scatter([cx], [cy], marker='D', c='purple', s=40, zorder=10)
            if dep.get('patrol_rangers'):
                ax_map.scatter([cx], [cy], marker='o', c='green', s=40, zorder=10)

        ax_map.set_title(title, fontsize=12)
        ax_leg.axis('off')

        sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
        sm.set_array([])
        cbar = plt.colorbar(sm, cax=ax_cbar)
        cbar.ax.tick_params(labelsize=8)

        for i, text in enumerate(stats):
            ax_leg.text(0.1, 0.9 - i * 0.1, text, transform=ax_leg.transAxes, fontsize=11)

        fig.savefig(os.path.join(out_dir, filename), dpi=150, bbox_inches='tight')
        plt.close(fig)

    # Normalized [0, max]
    pb_norm_vals = [g.get('protection_benefit_normalized', 0) for g in grids]
    _draw("Protection Benefit Heatmap (Normalized)",
          'protection_benefit_normalized', 'protection_heatmap.png',
          vmin=0, vmax=max(pb_norm_vals) if pb_norm_vals else 1)

    # Raw
    pb_raw_vals = [g.get('protection_benefit_raw', 0) for g in grids]
    _draw("Protection Benefit Heatmap (Raw)",
          'protection_benefit_raw', 'protection_heatmap_raw.png',
          vmin=0, vmax=max(pb_raw_vals) if pb_raw_vals else 1)


def main():
    parser = argparse.ArgumentParser(description="Visualize iteration results (lightweight version)")
    parser.add_argument('output_json', help="Output JSON file from iteration")
    parser.add_argument('--input', '-i', help="Input JSON (for grid info)", default=None)
    parser.add_argument('--out_dir', '-o', default='./figures', help="Output directory")
    
    args = parser.parse_args()
    
    os.makedirs(args.out_dir, exist_ok=True)
    
    out, out_map, hex_size = load_data(args.output_json, args.input)
    
    print(f"Generating lightweight visualizations for iteration...")
    draw_terrain_deployment_map(out, out_map, hex_size, args.out_dir)
    print(f"  saved: terrain_deployment_map.png")
    
    draw_risk_comparison(out, out_map, hex_size, args.out_dir)
    print(f"  saved: risk_comparison.png")
    
    draw_protection_heatmap(out, out_map, hex_size, args.out_dir)
    print(f"  saved: protection_heatmap.png")
    print(f"  saved: protection_heatmap_raw.png")
    
    print("Done!")


if __name__ == '__main__':
    main()