"""
Risk Analysis Script

Input: map-grid JSON (same format as protection_pipeline).
Flow: compute normalized composite risk -> generate risk heatmap + geo/species attribute map.
No DSSA optimization involved.

Output:
  1. risk_heatmap.png      — 综合风险指数热力图（YlOrRd 色阶）
  2. attributes_map.png    — 2×2 地理+物种属性图
  3. risk_results.json     — 每个网格的风险值及属性数据
"""

import json
import sys
import os
import math
import numpy as np
from typing import Dict, Tuple
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Polygon
from matplotlib.colors import Normalize
from matplotlib import cm
from typing import Dict, List, Tuple

_RISK_SRC = os.path.join(os.path.dirname(__file__), '..', 'riskIndex', 'src')
sys.path.insert(0, os.path.abspath(_RISK_SRC))
_RISK_DIR = os.path.join(os.path.dirname(__file__), '..', 'riskIndex')
sys.path.insert(0, os.path.abspath(_RISK_DIR))

from risk_model_wrapper import (
    MapConfig, GridInputData, TimeInputData, ModelConfigData,
    DistanceCalculator, convert_grid_input, convert_time_input, create_model_from_config,
)
from risk_model.core.species import Species
from risk_model.risk.density import DensityRiskCalculator
from risk_model.risk.composite import CompositeRiskCalculator
from risk_model.risk.human import HumanRiskCalculator
from risk_model.risk.environmental import EnvironmentalRiskCalculator
from risk_model.config import WeightManager
from risk_model.risk import RiskModel, HumanRiskWeights, EnvironmentalRiskWeights


# ---------------------------------------------------------------------------
# Terrain colors (from visualize_output.py)
# ---------------------------------------------------------------------------

TERRAIN_COLORS = {
    "SparseGrass": "#90EE90",
    "DenseGrass": "#228B22",
    "WaterHole": "#87CEEB",
    "SaltMarsh": "#E8DCC4",
    "Road": "#808080",
}

VEGETATION_COLORS = {
    'GRASSLAND': '#90EE90',
    'SHRUB':     '#C8A96E',
    'FOREST':    '#228B22',
    'WETLAND':   '#87CEEB',
    'BARE':      '#D3D3D3',
    'WATER':     '#4169E1',
    'ROAD':      '#808080',
}


# ---------------------------------------------------------------------------
# Hex geometry (from visualize_output.py)
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
# Layout helpers (from visualize_output.py)
# ---------------------------------------------------------------------------

def make_figure(has_colorbar=False):
    """
    返回 (fig, ax_map, ax_cbar_or_None, ax_legend)
    has_colorbar=True  → 三列：地图 | 颜色条 | 图例
    has_colorbar=False → 两列：地图 | 图例
    """
    fig = plt.figure(figsize=(14, 9))
    if has_colorbar:
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


def add_colorbar(fig, ax_cbar, cmap, norm, label):
    sm = cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, cax=ax_cbar)
    cbar.set_label(label, fontsize=10)


# ---------------------------------------------------------------------------
# Risk computation (from protection_pipeline.py)
# ---------------------------------------------------------------------------

def load_input(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def build_species_config(species_cfg: dict) -> dict:
    result = {}
    for name, cfg in species_cfg.items():
        result[name] = Species(
            name=name,
            weight=float(cfg.get('weight', 0.3)),
            rainy_season_multiplier=float(cfg.get('rainy_season_multiplier', 1.0)),
            dry_season_multiplier=float(cfg.get('dry_season_multiplier', 1.0))
        )
    return result


def compute_risk(data: dict) -> Tuple[Dict[int, float], Dict[int, float]]:
    """
    Compute both normalized and raw risk values.
    
    Returns:
        Tuple of (normalized_risks, raw_risks) dictionaries
    """
    map_cfg_raw = data['map_config']
    boundary_locations = map_cfg_raw.get('boundary_locations')
    if boundary_locations:
        normalized = []
        for item in boundary_locations:
            if isinstance(item, dict):
                normalized.append((item['x'], item['y']))
            else:
                normalized.append(tuple(item))
        boundary_locations = normalized

    map_config = MapConfig(
        map_width=map_cfg_raw['map_width'],
        map_height=map_cfg_raw['map_height'],
        boundary_type=map_cfg_raw.get('boundary_type', 'RECTANGLE'),
        road_locations=[tuple(p) for p in map_cfg_raw.get('road_locations', [])],
        water_locations=[tuple(p) for p in map_cfg_raw.get('water_locations', [])],
        boundary_locations=boundary_locations
    )

    time_raw = data.get('time', {})
    time_input = TimeInputData(
        hour_of_day=time_raw.get('hour_of_day', 12),
        season=time_raw.get('season', 'DRY')
    )

    distance_calc = DistanceCalculator(map_config)
    time_context = convert_time_input(time_input)

    cfg_raw = data.get('risk_model_config', {})
    model_config = ModelConfigData(
        risk_weights=cfg_raw.get('risk_weights'),
        human_risk_weights=cfg_raw.get('human_risk_weights'),
        environmental_risk_weights=cfg_raw.get('environmental_risk_weights')
    )
    model = create_model_from_config(model_config)

    if 'species_config' in data:
        species_cfg = build_species_config(data['species_config'])
        weight_manager = WeightManager()
        if cfg_raw.get('risk_weights'):
            weight_manager.set_risk_weights(**cfg_raw['risk_weights'])

        human_weights = None
        if cfg_raw.get('human_risk_weights'):
            human_weights = HumanRiskWeights(**cfg_raw['human_risk_weights'])

        env_weights = None
        if cfg_raw.get('environmental_risk_weights'):
            env_weights = EnvironmentalRiskWeights(**cfg_raw['environmental_risk_weights'])

        composite_calc = CompositeRiskCalculator(
            weight_manager=weight_manager,
            human_calculator=HumanRiskCalculator(weights=human_weights),
            environmental_calculator=EnvironmentalRiskCalculator(weights=env_weights),
            density_calculator=DensityRiskCalculator(species_config=species_cfg)
        )
        model = RiskModel(composite_calculator=composite_calc)

    grid_data_list = []
    id_order = []
    for g in data['grids']:
        gid = g['grid_id']
        grid_input = GridInputData(
            grid_id=str(gid),
            x=g.get('x', 0),
            y=g.get('y', 0),
            fire_risk=float(g.get('fire_risk', 0.0)),
            terrain_complexity=float(g.get('terrain_complexity', 0.0)),
            vegetation_type=g.get('vegetation_type', 'GRASSLAND'),
            species_densities=g.get('species_densities', {})
        )
        grid_obj, env_obj, density_obj = convert_grid_input(grid_input, distance_calc)
        grid_data_list.append((grid_obj, env_obj, density_obj))
        id_order.append(gid)

    use_temporal = data.get('use_temporal_factors', False)
    results = model.calculate_batch(grid_data_list, time_context, use_temporal_factors=use_temporal)
    
    normalized_risks = {id_order[i]: float(r.normalized_risk) for i, r in enumerate(results)}
    raw_risks = {id_order[i]: float(r.raw_risk) for i, r in enumerate(results)}
    
    return normalized_risks, raw_risks


# ---------------------------------------------------------------------------
# Plot 1: Risk heatmap (following visualize_output.py style)
# ---------------------------------------------------------------------------

def plot_risk_heatmap(grids: list, risk_map: Dict[int, float],
                      hex_size: float = 1.0, save_path: str = None):
    cmap = matplotlib.colormaps.get_cmap("YlOrRd")
    # 使用统一的 [0, 1] 范围便于跨场景对比
    norm = Normalize(vmin=0, vmax=1)

    fig, ax, ax_cbar, ax_leg = make_figure(has_colorbar=True)

    for g in grids:
        gid = g['grid_id']
        risk = risk_map.get(gid, 0.0)
        cx, cy = grid_center(g["q"], g["r"], hex_size)
        draw_hex(ax, cx, cy, hex_size * 0.97, facecolor=cmap(norm(risk)))

    setup_map_ax(ax, grids, hex_size)
    ax.set_title("Composite Risk Index Heatmap (Normalized)", fontsize=13, fontweight="bold", pad=8)

    add_colorbar(fig, ax_cbar, cmap, norm, "Normalized Risk [0, 1]")

    risk_vals = list(risk_map.values())
    items = [
        ("Summary", None, True),
        ("Total Grids", str(len(risk_vals)), False),
        ("Risk Min", f"{min(risk_vals):.4f}", False),
        ("Risk Max", f"{max(risk_vals):.4f}", False),
        ("Risk Mean", f"{np.mean(risk_vals):.4f}", False),
    ]
    y = 0.97
    for label, value, bold in items:
        text = label if value is None else f"{label}: {value}"
        ax_leg.text(0.05, y, text, transform=ax_leg.transAxes,
                    fontsize=9, va="top",
                    fontweight="bold" if bold else "normal",
                    fontfamily="monospace")
        y -= 0.09

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"  Risk heatmap saved -> {save_path}")
    plt.close(fig)


def plot_raw_risk_heatmap(grids: list, raw_risk_map: Dict[int, float],
                          hex_size: float = 1.0, save_path: str = None):
    """Plot raw risk heatmap (preserves temporal factors).
    
    Uses [0, 1] range for colorbar to enable cross-scenario comparison.
    """
    cmap = matplotlib.colormaps.get_cmap("YlOrRd")
    
    raw_vals = list(raw_risk_map.values())
    if not raw_vals:
        return
    
    # 使用统一的 [0, 1] 范围便于跨场景对比
    # 注意：原始风险值可能超过 1.0，会被截断到 [0, 1]
    norm = Normalize(vmin=0, vmax=1)

    fig, ax, ax_cbar, ax_leg = make_figure(has_colorbar=True)

    for g in grids:
        gid = g['grid_id']
        risk = raw_risk_map.get(gid, 0.0)
        cx, cy = grid_center(g["q"], g["r"], hex_size)
        # 颜色映射会自动截断超过 1.0 的值
        draw_hex(ax, cx, cy, hex_size * 0.97, facecolor=cmap(norm(risk)))

    setup_map_ax(ax, grids, hex_size)
    ax.set_title("Raw Risk Index Heatmap (with Temporal Factors)", fontsize=13, fontweight="bold", pad=8)

    add_colorbar(fig, ax_cbar, cmap, norm, "Raw Risk [0, 1]")

    items = [
        ("Summary", None, True),
        ("Total Grids", str(len(raw_vals)), False),
        ("Risk Min", f"{min(raw_vals):.6f}", False),
        ("Risk Max", f"{max(raw_vals):.6f}", False),
        ("Risk Mean", f"{np.mean(raw_vals):.6f}", False),
        ("Note", "Values > 1.0 shown as max color", False),
    ]
    y = 0.97
    for label, value, bold in items:
        text = label if value is None else f"{label}: {value}"
        ax_leg.text(0.05, y, text, transform=ax_leg.transAxes,
                    fontsize=9, va="top",
                    fontweight="bold" if bold else "normal",
                    fontfamily="monospace")
        y -= 0.09

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"  Raw risk heatmap saved -> {save_path}")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Plot 2: Geographic & Species attributes (2x2 subplots)
# ---------------------------------------------------------------------------

def plot_attributes_map(grids: list, hex_size: float = 1.0, save_path: str = None):
    """
    2x2 subplots following visualize_output.py layout:
      [0,0] Vegetation type (categorical)
      [0,1] Terrain complexity (continuous)
      [1,0] Fire risk (continuous)
      [1,1] Total species density (continuous)
    """
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle('Geographic & Species Attribute Map', fontsize=14, fontweight='bold')

    # Compute bounds
    xs, ys = [], []
    for g in grids:
        cx, cy = grid_center(g["q"], g["r"], hex_size)
        xs.append(cx); ys.append(cy)
    minx, maxx = min(xs) - hex_size - 1, max(xs) + hex_size + 1
    miny, maxy = min(ys) - hex_size - 1, max(ys) + hex_size + 1

    # [0,0] Vegetation type
    ax = axes[0, 0]
    veg_types = sorted({g.get('vegetation_type', 'GRASSLAND') for g in grids})
    fallback_cmap = matplotlib.colormaps['tab10']
    fallback_colors = {v: fallback_cmap(i / max(len(veg_types) - 1, 1)) for i, v in enumerate(veg_types)}

    for g in grids:
        vtype = g.get('vegetation_type', 'GRASSLAND')
        color = VEGETATION_COLORS.get(vtype, fallback_colors.get(vtype, '#FFFFFF'))
        cx, cy = grid_center(g["q"], g["r"], hex_size)
        draw_hex(ax, cx, cy, hex_size * 0.97, facecolor=color)

    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)
    ax.set_aspect('equal')
    ax.set_title('Vegetation Type', fontsize=11, fontweight='bold')
    ax.axis('off')

    legend_elems = [
        mpatches.Patch(color=VEGETATION_COLORS.get(v, fallback_colors.get(v, '#FFFFFF')), label=v)
        for v in veg_types
    ]
    ax.legend(handles=legend_elems, loc='upper right', fontsize=8, ncol=1)

    # [0,1] Terrain complexity
    ax = axes[0, 1]
    tc_vals = [float(g.get('terrain_complexity', 0.0)) for g in grids]
    tc_min, tc_max = min(tc_vals), max(tc_vals)
    tc_norm = Normalize(vmin=tc_min, vmax=tc_max)
    tc_cmap = matplotlib.colormaps.get_cmap('Blues')

    for g, v in zip(grids, tc_vals):
        cx, cy = grid_center(g["q"], g["r"], hex_size)
        draw_hex(ax, cx, cy, hex_size * 0.97, facecolor=tc_cmap(tc_norm(v)))

    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)
    ax.set_aspect('equal')
    ax.set_title('Terrain Complexity', fontsize=11, fontweight='bold')
    ax.axis('off')

    sm = cm.ScalarMappable(cmap=tc_cmap, norm=tc_norm)
    sm.set_array([])
    cbar = plt.colorbar(sm, ax=ax, shrink=0.8)
    cbar.set_label('Complexity', fontsize=9)

    # [1,0] Fire risk
    ax = axes[1, 0]
    fr_vals = [float(g.get('fire_risk', 0.0)) for g in grids]
    fr_min, fr_max = min(fr_vals), max(fr_vals)
    fr_norm = Normalize(vmin=fr_min, vmax=fr_max)
    fr_cmap = matplotlib.colormaps.get_cmap('Reds')

    for g, v in zip(grids, fr_vals):
        cx, cy = grid_center(g["q"], g["r"], hex_size)
        draw_hex(ax, cx, cy, hex_size * 0.97, facecolor=fr_cmap(fr_norm(v)))

    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)
    ax.set_aspect('equal')
    ax.set_title('Fire Risk', fontsize=11, fontweight='bold')
    ax.axis('off')

    sm = cm.ScalarMappable(cmap=fr_cmap, norm=fr_norm)
    sm.set_array([])
    cbar = plt.colorbar(sm, ax=ax, shrink=0.8)
    cbar.set_label('Risk', fontsize=9)

    # [1,1] Total species density
    ax = axes[1, 1]
    def total_density(g):
        sd = g.get('species_densities', {})
        return sum(float(v) for v in sd.values()) if sd else 0.0

    sp_vals = [total_density(g) for g in grids]
    sp_min, sp_max = min(sp_vals), max(sp_vals)
    sp_norm = Normalize(vmin=sp_min, vmax=sp_max)
    sp_cmap = matplotlib.colormaps.get_cmap('Greens')

    for g, v in zip(grids, sp_vals):
        cx, cy = grid_center(g["q"], g["r"], hex_size)
        draw_hex(ax, cx, cy, hex_size * 0.97, facecolor=sp_cmap(sp_norm(v)))

    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)
    ax.set_aspect('equal')
    ax.set_title('Total Species Density', fontsize=11, fontweight='bold')
    ax.axis('off')

    sm = cm.ScalarMappable(cmap=sp_cmap, norm=sp_norm)
    sm.set_array([])
    cbar = plt.colorbar(sm, ax=ax, shrink=0.8)
    cbar.set_label('Density', fontsize=9)

    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"  Attributes map saved -> {save_path}")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(input_path: str, output_dir: str, hex_size: float = None):
    try:
        os.makedirs(output_dir, exist_ok=True)
        print(f"[1/3] Loading input: {input_path}")
        data = load_input(input_path)
        print(f"      Loaded {len(data.get('grids', []))} grids")

        # Auto-detect hex_size from input JSON if not provided
        grids = data['grids']
        if hex_size is None:
            if grids and 'hex_size' in grids[0]:
                hex_size = float(grids[0]['hex_size'])
                print(f"      Auto-detected hex_size: {hex_size}")
            else:
                hex_size = 1.0
                print(f"      No hex_size in input, using default: {hex_size}")
        else:
            print(f"      Using provided hex_size: {hex_size}")

        print("[2/3] Computing composite risk index...")
        normalized_risks, raw_risks = compute_risk(data)
        print(f"      Computed risk for {len(normalized_risks)} grids")

        norm_vals = list(normalized_risks.values())
        raw_vals = list(raw_risks.values())
        print(f"      Normalized: min={min(norm_vals):.4f}  max={max(norm_vals):.4f}  mean={np.mean(norm_vals):.4f}")
        print(f"      Raw       : min={min(raw_vals):.6f}  max={max(raw_vals):.6f}  mean={np.mean(raw_vals):.6f}")
        
        # Calculate temporal factor if applicable
        temporal_factor = None
        if min(norm_vals) > 0 and min(raw_vals) > 0:
            temporal_factor = np.mean(raw_vals) / np.mean(norm_vals) if np.mean(norm_vals) > 0 else None

        print("[3/3] Generating maps...")
        plot_risk_heatmap(grids, normalized_risks, hex_size,
                          save_path=os.path.join(output_dir, 'risk_heatmap.png'))
        plot_raw_risk_heatmap(grids, raw_risks, hex_size,
                              save_path=os.path.join(output_dir, 'raw_risk_heatmap.png'))
        plot_attributes_map(grids, hex_size,
                            save_path=os.path.join(output_dir, 'attributes_map.png'))

        # Save risk results as JSON
        result_path = os.path.join(output_dir, 'risk_results.json')
        with open(result_path, 'w', encoding='utf-8') as f:
            summary = {
                'total_grids': len(norm_vals),
                'normalized_risk_min': round(min(norm_vals), 6),
                'normalized_risk_max': round(max(norm_vals), 6),
                'normalized_risk_mean': round(float(np.mean(norm_vals)), 6),
                'raw_risk_min': round(min(raw_vals), 6),
                'raw_risk_max': round(max(raw_vals), 6),
                'raw_risk_mean': round(float(np.mean(raw_vals)), 6),
            }
            if temporal_factor is not None:
                summary['temporal_factor'] = round(temporal_factor, 4)
            
            json.dump({
                'summary': summary,
                'grids': [
                    {
                        'grid_id': g['grid_id'],
                        'q': g['q'],
                        'r': g['r'],
                        'normalized_risk': round(normalized_risks.get(g['grid_id'], 0.0), 6),
                        'raw_risk': round(raw_risks.get(g['grid_id'], 0.0), 6),
                        'vegetation_type': g.get('vegetation_type', ''),
                        'terrain_complexity': g.get('terrain_complexity', 0.0),
                        'fire_risk': g.get('fire_risk', 0.0),
                        'species_densities': g.get('species_densities', {}),
                    }
                    for g in grids
                ]
            }, f, indent=2, ensure_ascii=False)
        print(f"  Risk results saved -> {result_path}")
        print("\nDone.")
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description="Risk Analysis: compute composite risk index and generate heatmap + attribute maps."
    )
    parser.add_argument('input', help='Input JSON path (same format as protection_pipeline)')
    parser.add_argument('output_dir', help='Output directory for generated maps and JSON')
    parser.add_argument('--hex-size', type=float, default=None,
                        help='Hex cell size for rendering (auto-detected from input if not provided)')
    args = parser.parse_args()

    run(args.input, args.output_dir, hex_size=args.hex_size)


# DEBUG: Add this at the very end to test (disabled)
# print("DEBUG: Module loaded successfully", flush=True)
