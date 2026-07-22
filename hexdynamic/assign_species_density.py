"""
assign_species_density.py
基于 Etosha 国家公园生态模型的物种密度分配脚本。

核心特征：
- 环盐沼分布（Gaussian Ring）：动物沿盐沼边缘环带分布，中央盐沼低密度
- 水源驱动：水坑是超级热点节点，动物围绕水坑聚集
- 道路回避：物种分布优先选择距离道路远的水坑（远离人为干扰）
- 多物种共存：Zone B（水坑环带）形成 Multi-species Hotspot
- 大象生态工程师效应：大象改变栖息地结构，犀牛回避大象高密度区（降低密度，非消除）
- 鸟类-水源-盐沼耦合：鸟类与水源和盐沼边缘强相关

分区模型：
- Zone A（盐沼核心区）：低资源，低动物密度，雨季短暂吸引鸟类
- Zone B（水坑环带）：核心热点，大象/犀牛/鸟类多物种聚集
- Zone C（外围灌木带）：犀牛长期栖息区，竞争压力较低

HSI（栖息适宜度指数）模型：
  Rhino:    HSI = w_w*water + w_v*veg + w_r*ring - w_c*elephant_impact
  Elephant: HSI = w_w*water + w_v*veg + w_r*ring
  Bird:     HSI = w_w*water + w_s*saltmarsh + w_v*veg

道路回避约束：
  每个水坑根据其到最近道路的距离计算"道路回避惩罚"：
    penalty = road_penalty * max(0, 1 - road_dist / road_far_threshold)
  道路旁的水坑 penalty = road_penalty（最大），远离道路的水坑 penalty = 0。
  水坑的有效距离 = 实际六边形距离 + penalty，从而降低靠近道路水坑的吸引力。

环因子（Gaussian Ring）：
  ring_factor = exp(-((d_saltmarsh - ring_peak)^2) / (2 * ring_sigma^2))
  在盐沼边缘 ring_peak 步处形成密度峰值环带

密度公式：
  density = dmin + (dmax - dmin) * herd_factor * (0.4 + 0.6 * hsi_norm)

用法：
    python assign_species_density.py input.json
    python assign_species_density.py input.json -o output.json
    python assign_species_density.py input.json --seed 42
    python assign_species_density.py input.json --visualize
    python assign_species_density.py input.json --road-penalty 10 --road-far-threshold 15
"""

import argparse
import heapq
import json
import math
import os
import random
import sys
from collections import deque
from typing import Dict, List, Set, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

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

VEGETATION_INDEX = {
    "DenseGrass": 0.8,
    "SparseGrass": 0.5,
    "WaterHole":   0.2,
    "SaltMarsh":   0.1,
    "Road":        0.0,
}

HEX_DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1)]

# 道路回避约束默认参数
# road_far_threshold: 水坑距道路 >= 此值时无惩罚（步）
# road_penalty: 道路旁水坑的最大有效距离惩罚（步）
DEFAULT_ROAD_FAR_THRESHOLD = 15
DEFAULT_ROAD_PENALTY = 10

SPECIES_PROFILES = {
    "rhino": {
        "habitat_terrains": {"SparseGrass"},
        "prohibited_terrains": {"DenseGrass", "WaterHole", "SaltMarsh", "Road"},
        "hsi_weights": {"water": 0.40, "vegetation": 0.10, "ring": 0.30, "competition": 0.10},
        "water_decay": 10,
        "ring_peak": 5,
        "ring_sigma": 15,
        "impact_decay": 4,
        "herd_radius": 6,
        "num_herds": (2, 4),
        "density_range": (0.4, 1.0),
        "target_ratio": 5,
    },
    "elephant": {
        "habitat_terrains": {"SparseGrass", "DenseGrass"},
        "prohibited_terrains": {"WaterHole", "SaltMarsh", "Road"},
        "hsi_weights": {"water": 0.35, "vegetation": 0.15, "ring": 0.50, "competition": 0.0},
        "water_decay": 10,
        "ring_peak": 8,
        "ring_sigma": 20,
        "impact_decay": 15,
        "herd_radius": 8,
        "num_herds": (2, 3),
        "density_range": (0.3, 0.9),
        "target_ratio": 5,
    },
    "bird": {
        "habitat_terrains": {"SaltMarsh", "WaterHole"},
        "prohibited_terrains": {"Road"},
        "hsi_weights": {"water": 0.25, "saltmarsh": 0.55, "vegetation": 0.20},
        "water_decay": 6,
        "saltmarsh_decay": 5,
        "herd_radius": 5,
        "num_herds": (3, 6),
        "density_range": (0.5, 1.0),
        "target_ratio": 5,
    },
}


def build_neighbors_map(grids: List[dict]) -> Dict[int, List[int]]:
    idx_map = {}
    for i, g in enumerate(grids):
        key = (g["q"], g["r"])
        idx_map[key] = i
    neighbors = {}
    for i, g in enumerate(grids):
        q, r = g["q"], g["r"]
        neighbors[i] = []
        for dq, dr in HEX_DIRS:
            nk = (q + dq, r + dr)
            if nk in idx_map:
                neighbors[i].append(idx_map[nk])
    return neighbors


def bfs_distance(grids, neighbors, source_indices):
    dist = {i: 999 for i in range(len(grids))}
    queue = deque()
    for idx in source_indices:
        dist[idx] = 0
        queue.append(idx)
    while queue:
        idx = queue.popleft()
        for nb in neighbors.get(idx, []):
            if dist[idx] + 1 < dist[nb]:
                dist[nb] = dist[idx] + 1
                queue.append(nb)
    return dist


def dijkstra_distance_weighted_sources(grids, neighbors, source_indices, source_costs):
    """带源点初始代价的多源最短路（Dijkstra）。

    每个源点 source_indices[k] 的初始代价为 source_costs[k]，
    用于实现"远离道路的水坑更有吸引力"的约束：
      水坑的有效距离 = 实际六边形距离 + 该水坑的道路回避惩罚
    """
    dist = {i: float('inf') for i in range(len(grids))}
    pq = []
    for idx, cost in zip(source_indices, source_costs):
        if cost < dist.get(idx, float('inf')):
            dist[idx] = cost
            heapq.heappush(pq, (cost, idx))
    while pq:
        d, idx = heapq.heappop(pq)
        if d > dist[idx]:
            continue
        for nb in neighbors.get(idx, []):
            nd = d + 1
            if nd < dist[nb]:
                dist[nb] = nd
                heapq.heappush(pq, (nd, nb))
    # 将无穷大替换为 999 以保持与 bfs_distance 一致的语义
    return {i: (d if d != float('inf') else 999) for i, d in dist.items()}


def compute_spatial_features(grids, neighbors,
                             road_far_threshold=DEFAULT_ROAD_FAR_THRESHOLD,
                             road_penalty=DEFAULT_ROAD_PENALTY):
    """计算每个网格到水坑、盐沼、道路的距离。

    水坑距离使用加权多源 Dijkstra：靠近道路的水坑被附加惩罚，
    使物种分布优先选择远离道路的水坑。
    """
    water_sources = [i for i, g in enumerate(grids) if g["terrain_type"] == "WaterHole"]
    saltmarsh_sources = [i for i, g in enumerate(grids) if g["terrain_type"] == "SaltMarsh"]
    road_sources = [i for i, g in enumerate(grids) if g["terrain_type"] == "Road"]

    saltmarsh_dist = bfs_distance(grids, neighbors, saltmarsh_sources) if saltmarsh_sources else {i: 999 for i in range(len(grids))}

    if water_sources:
        if road_sources and road_penalty > 0:
            # 计算每个水坑到最近道路的距离
            road_dist = bfs_distance(grids, neighbors, road_sources)
            source_costs = []
            for wh_idx in water_sources:
                r_dist = road_dist.get(wh_idx, 999)
                # 道路旁水坑惩罚最大，远离道路(>=threshold)惩罚为 0
                penalty = road_penalty * max(0.0, 1.0 - r_dist / max(1, road_far_threshold))
                source_costs.append(penalty)
            water_dist = dijkstra_distance_weighted_sources(
                grids, neighbors, water_sources, source_costs)
        else:
            water_dist = bfs_distance(grids, neighbors, water_sources)
    else:
        water_dist = {i: 999 for i in range(len(grids))}

    return water_dist, saltmarsh_dist


def compute_hsi(grids, species, profile, water_dist, saltmarsh_dist, elephant_impact=None):
    weights = profile["hsi_weights"]
    hsi = {}
    for i, g in enumerate(grids):
        tt = g["terrain_type"]
        water_factor = math.exp(-water_dist.get(i, 999) / profile["water_decay"])
        veg_factor = VEGETATION_INDEX.get(tt, 0.0)

        if "saltmarsh" in weights:
            saltmarsh_factor = math.exp(-saltmarsh_dist.get(i, 999) / profile["saltmarsh_decay"])
            hsi[i] = (weights.get("water", 0) * water_factor
                      + weights.get("saltmarsh", 0) * saltmarsh_factor
                      + weights.get("vegetation", 0) * veg_factor)
        else:
            if tt == "SaltMarsh":
                ring_factor = 0.0
            else:
                d = saltmarsh_dist.get(i, 999)
                ring_peak = profile.get("ring_peak", 5)
                ring_sigma = profile.get("ring_sigma", 8)
                ring_factor = math.exp(-((d - ring_peak) ** 2) / (2 * ring_sigma ** 2))

            competition_factor = 0.0
            if elephant_impact and weights.get("competition", 0) > 0:
                competition_factor = elephant_impact.get(i, 0)

            hsi[i] = (weights.get("water", 0) * water_factor
                      + weights.get("vegetation", 0) * veg_factor
                      + weights.get("ring", 0) * ring_factor
                      - weights.get("competition", 0) * competition_factor)

    return hsi


def bfs_expand(seeds, max_count, neighbors, species_assigned, is_result):
    result = []
    visited = set()
    queue = deque()
    max_visited = max_count * 10
    for s in seeds:
        visited.add(s)
        queue.append(s)
    while queue and len(result) < max_count and len(visited) < max_visited:
        idx = queue.popleft()
        for nb in neighbors.get(idx, []):
            if nb not in visited and len(visited) < max_visited:
                visited.add(nb)
                queue.append(nb)
        if idx in species_assigned:
            continue
        if not is_result(idx):
            continue
        result.append(idx)
        species_assigned.add(idx)
    return result


def _assign_one_species(grids, species, profile, neighbors, water_dist, saltmarsh_dist,
                        total, elephant_indices=None):
    dmin, dmax = profile["density_range"]
    prohibited = profile.get("prohibited_terrains", set())

    elephant_impact = None
    if profile["hsi_weights"].get("competition", 0) > 0 and elephant_indices:
        e_dist = bfs_distance(grids, neighbors, elephant_indices)
        impact_decay = profile.get("impact_decay", 10)
        elephant_impact = {i: math.exp(-d / impact_decay) for i, d in e_dist.items()}

    hsi = compute_hsi(grids, species, profile, water_dist, saltmarsh_dist, elephant_impact)

    is_result = lambda idx, _p=prohibited: grids[idx]["terrain_type"] not in _p
    candidates = [i for i in range(total) if is_result(i)]
    if not candidates:
        return 0, []

    candidates.sort(key=lambda i: hsi.get(i, 0), reverse=True)

    num_herds = random.randint(*profile["num_herds"])
    total_max = max(1, total * profile["target_ratio"] // 100)
    herd_max = max(3, total_max // num_herds)

    min_seed_dist = max(5, int(math.sqrt(total) / 4))
    seed_indices = []
    for idx in candidates:
        if len(seed_indices) >= num_herds:
            break
        gq, gr = grids[idx]["q"], grids[idx]["r"]
        too_close = any(
            ((grids[si]["q"] - gq) ** 2 + (grids[si]["r"] - gr) ** 2) ** 0.5 < min_seed_dist
            for si in seed_indices
        )
        if not too_close:
            seed_indices.append(idx)

    hsi_max = max(hsi.get(i, 0.001) for i in candidates)
    if hsi_max <= 0:
        hsi_max = 1.0

    species_assigned = set()
    count = 0
    new_elephant_indices = []
    for seed_idx in seed_indices:
        expanded = bfs_expand([seed_idx], herd_max, neighbors, species_assigned, is_result)
        sq, sr = grids[seed_idx]["q"], grids[seed_idx]["r"]

        for idx in expanded:
            g = grids[idx]
            d_center = ((g["q"] - sq) ** 2 + (g["r"] - sr) ** 2) ** 0.5
            herd_factor = math.exp(-d_center / profile["herd_radius"])
            hsi_norm = max(0.0, hsi.get(idx, 0)) / hsi_max

            combined = herd_factor * (0.4 + 0.6 * hsi_norm)
            val = dmin + (dmax - dmin) * combined
            g["species_densities"][species] = round(max(dmin, min(dmax, val)), 2)
            if "elephant" in species.lower():
                new_elephant_indices.append(idx)
            count += 1

    return count, new_elephant_indices


def assign_species_densities(grids: List[dict], seed: int = None,
                             road_far_threshold: float = DEFAULT_ROAD_FAR_THRESHOLD,
                             road_penalty: float = DEFAULT_ROAD_PENALTY) -> Dict[str, int]:
    if seed is not None:
        random.seed(seed)

    species_names = []
    for g in grids:
        for sp in g.get("species_densities", {}):
            if sp not in species_names:
                species_names.append(sp)

    for g in grids:
        for sp in species_names:
            g["species_densities"][sp] = 0.0

    total = len(grids)
    if total == 0:
        return {}

    neighbors = build_neighbors_map(grids)
    water_dist, saltmarsh_dist = compute_spatial_features(
        grids, neighbors,
        road_far_threshold=road_far_threshold,
        road_penalty=road_penalty)

    stats = {}
    elephant_indices = []

    non_bird = [sp for sp in species_names if "bird" not in sp.lower()]
    bird_sp = next((sp for sp in species_names if "bird" in sp.lower()), None)

    ordered = []
    for sp in non_bird:
        if "elephant" in sp.lower():
            ordered.insert(0, sp)
        else:
            ordered.append(sp)

    for species in ordered:
        profile = SPECIES_PROFILES.get(species, SPECIES_PROFILES["rhino"])
        count, new_ei = _assign_one_species(
            grids, species, profile, neighbors, water_dist, saltmarsh_dist,
            total, elephant_indices if elephant_indices else None)
        stats[species] = count
        elephant_indices.extend(new_ei)

    if bird_sp:
        profile = SPECIES_PROFILES["bird"]
        count, _ = _assign_one_species(
            grids, bird_sp, profile, neighbors, water_dist, saltmarsh_dist,
            total)
        stats[bird_sp] = count

    return stats


def classify_zones(grids, water_dist, saltmarsh_dist):
    zone_a = zone_b = zone_c = 0
    water_threshold = 15
    for i, g in enumerate(grids):
        tt = g["terrain_type"]
        if tt == "SaltMarsh":
            zone_a += 1
        elif water_dist.get(i, 999) <= water_threshold:
            zone_b += 1
        else:
            zone_c += 1
    return {"Zone A (Salt Pan Core)": zone_a, "Zone B (Waterhole Ring)": zone_b, "Zone C (Peripheral Shrub)": zone_c}


def verify_constraints(grids: List[dict]) -> List[str]:
    violations = []
    for g in grids:
        sd = g.get("species_densities", {})
        tt = g["terrain_type"]
        for sp in ["rhino"]:
            if sd.get(sp, 0) > 0 and tt in ("DenseGrass", "WaterHole", "SaltMarsh", "Road"):
                violations.append(f"Grid {g['grid_id']}: {sp} in {tt}")
        for sp in ["elephant"]:
            if sd.get(sp, 0) > 0 and tt in ("WaterHole", "SaltMarsh", "Road"):
                violations.append(f"Grid {g['grid_id']}: {sp} in {tt}")
    return violations


def hex_corners(cx, cy, size):
    return [
        (cx + size * math.cos(math.pi / 3 * i - math.pi / 6),
         cy + size * math.sin(math.pi / 3 * i - math.pi / 6))
        for i in range(6)
    ]


def grid_center(q, r, size):
    x = size * math.sqrt(3) * (q + r / 2)
    y = size * 1.5 * r
    return x, y


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


def plot_species_density_map(grids, hex_size, save_path):
    all_species = sorted({sp for g in grids for sp, d in g.get("species_densities", {}).items() if d > 0})
    if not all_species:
        print("  No species density to visualize.")
        return

    stats_text = _species_stats_text(grids, all_species)
    n_stats_lines = stats_text.count("\n") + 1
    stats_height = 0.4 + n_stats_lines * 0.06

    fig = plt.figure(figsize=(14, 10 + stats_height))
    ax = fig.add_axes([0.02, stats_height / (10 + stats_height), 0.96, 10 / (10 + stats_height)])

    for g in grids:
        cx, cy = grid_center(g["q"], g["r"], hex_size)
        fc = TERRAIN_COLORS.get(g.get("terrain_type", ""), "#dddddd")
        corners = hex_corners(cx, cy, hex_size * 0.97)
        ax.fill(*zip(*corners), facecolor=fc, edgecolor="black", linewidth=0.4, alpha=0.5)

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
            ax.scatter(cx + ox, cy, marker=style["marker"], s=size,
                       color=style["color"], edgecolors="black",
                       linewidths=0.4, alpha=0.85, zorder=4)

    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title("Species Density Map (Etosha Ring Model)", fontsize=13, fontweight="bold", pad=8)

    terrain_handles = [mpatches.Patch(facecolor=c, edgecolor="black", linewidth=0.5, alpha=0.5, label=t)
                       for t, c in TERRAIN_COLORS.items()]
    species_handles = [
        plt.Line2D([0], [0], marker=SPECIES_STYLE.get(sp, {}).get("marker", "o"),
                   color="w", markerfacecolor=SPECIES_STYLE.get(sp, {}).get("color", "#333"),
                   markeredgecolor="black", markersize=9, label=f"{sp} (size ~ density)")
        for sp in all_species
    ]
    ax.legend(handles=terrain_handles + species_handles, loc="upper right", fontsize=8, framealpha=0.8)

    fig.text(0.02, 0.02, stats_text, fontsize=9, fontfamily="monospace",
             verticalalignment="bottom",
             bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor="gray", alpha=0.9))

    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved: {save_path}")


def plot_species_density_panels(grids, hex_size, save_path, grid_dpi=20, save_dpi=150):
    import matplotlib.colors as mcolors
    from matplotlib.cm import ScalarMappable

    all_species = sorted({sp for g in grids for sp, d in g.get("species_densities", {}).items() if d > 0})
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
        cbar.set_label("Density", fontsize=8)
        cbar.ax.tick_params(labelsize=7)

        fig.text(left + panel_w * 0.44, bottom + panel_h - title_h * 0.3,
                 f"{sp.capitalize()} Density", fontsize=11, fontweight="bold",
                 ha="center", va="bottom")

    comp_idx = n_species
    comp_row = comp_idx // ncols
    comp_col = comp_idx % ncols
    comp_left = comp_col * (panel_w + gap_frac_w)
    comp_bottom = (nrows - 1 - comp_row) * (panel_h + gap_frac_h) + 0.06

    ax_comp = fig.add_axes([comp_left, comp_bottom, panel_w, panel_h - title_h])
    _draw_composite(ax_comp, grids, hex_size, all_species)
    fig.text(comp_left + panel_w * 0.5, comp_bottom + panel_h - title_h * 0.3,
             "Composite Overview", fontsize=11, fontweight="bold", ha="center", va="bottom")

    legend_items = []
    for sp in all_species:
        fill_color = SPECIES_STYLE.get(sp, {}).get("fill_color", "#333")
        legend_items.append(mpatches.Patch(facecolor=fill_color, edgecolor="black",
                                           linewidth=0.5, alpha=0.7, label=sp))
    terrain_items = [mpatches.Patch(facecolor=c, edgecolor="black", linewidth=0.5, alpha=0.5, label=t)
                     for t, c in TERRAIN_COLORS.items()]
    ax_comp.legend(handles=terrain_items + legend_items, loc="upper right", fontsize=7, framealpha=0.8)

    fig.text(0.02, 0.01, stats_text, fontsize=9, fontfamily="monospace",
             verticalalignment="bottom",
             bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor="gray", alpha=0.9))

    fig.suptitle("Species Density Panels (Etosha Ring Model)", fontsize=14, fontweight="bold", y=0.99)
    fig.savefig(save_path, dpi=save_dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved: {save_path}")


def parse_args():
    p = argparse.ArgumentParser(
        description="Etosha ecological model - species density assignment with ring distribution",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("input", help="Input pipeline JSON file path")
    p.add_argument("-o", "--output", default=None,
                   help="Output file path (default: overwrite input)")
    p.add_argument("--seed", type=int, default=None,
                   help="Random seed (reproducible)")
    p.add_argument("--visualize", action="store_true",
                   help="Generate species density preview map")
    p.add_argument("--no-verify", action="store_true",
                   help="Skip constraint verification")
    p.add_argument("--road-penalty", type=float, default=DEFAULT_ROAD_PENALTY,
                   help="Max effective-distance penalty for waterholes next to roads (default: %(default)s)")
    p.add_argument("--road-far-threshold", type=float, default=DEFAULT_ROAD_FAR_THRESHOLD,
                   help="Waterholes >= this many steps from a road have zero penalty (default: %(default)s)")
    p.add_argument("--no-road-avoidance", action="store_true",
                   help="Disable road-avoidance constraint (treat all waterholes equally)")
    return p.parse_args()


def main():
    args = parse_args()

    print(f"Loading: {args.input}")
    with open(args.input, 'r', encoding='utf-8') as f:
        data = json.load(f)

    grids = data.get("grids", [])
    if not grids:
        print("Error: no grids found in input JSON")
        sys.exit(1)

    print(f"  Total grids: {len(grids)}")

    terrain_counts = {}
    for g in grids:
        tt = g["terrain_type"]
        terrain_counts[tt] = terrain_counts.get(tt, 0) + 1
    for tt, cnt in sorted(terrain_counts.items()):
        print(f"  {tt}: {cnt}")

    neighbors = build_neighbors_map(grids)
    road_penalty = 0.0 if args.no_road_avoidance else args.road_penalty
    road_far_threshold = args.road_far_threshold
    water_dist, saltmarsh_dist = compute_spatial_features(
        grids, neighbors,
        road_far_threshold=road_far_threshold,
        road_penalty=road_penalty)
    zones = classify_zones(grids, water_dist, saltmarsh_dist)
    print("\n  Zone classification:")
    for z, cnt in zones.items():
        print(f"    {z}: {cnt} grids ({100 * cnt / len(grids):.1f}%)")

    print(f"\nAssigning species densities (seed={args.seed})...")
    print("  Model: Etosha National Park - Ring distribution around salt pan")
    print("  Features: Gaussian ring factor, multi-species overlap, elephant impact field")
    if road_penalty > 0:
        print(f"  Road avoidance: penalty={road_penalty}, far_threshold={road_far_threshold}")
    else:
        print("  Road avoidance: disabled")
    stats = assign_species_densities(
        grids, seed=args.seed,
        road_far_threshold=road_far_threshold,
        road_penalty=road_penalty)

    for sp, cnt in stats.items():
        print(f"  {sp}: {cnt} grids ({100 * cnt / len(grids):.1f}%)")

    overlap = sum(1 for g in grids
                  if sum(1 for sp in g.get("species_densities", {})
                         if g["species_densities"][sp] > 0) > 1)
    print(f"  Multi-species hotspot grids: {overlap}")

    if not args.no_verify:
        violations = verify_constraints(grids)
        if violations:
            print(f"\n  WARNING: {len(violations)} constraint violations found!")
            for v in violations[:10]:
                print(f"    {v}")
            if len(violations) > 10:
                print(f"    ... and {len(violations) - 10} more")
        else:
            print("  All constraints satisfied.")

    output_path = args.output or args.input
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {output_path}")

    if args.visualize:
        hex_size = 1.0
        for g in grids:
            if g.get("hex_size"):
                hex_size = float(g["hex_size"])
                break
        viz_path = os.path.splitext(output_path)[0] + "_species_density.png"
        plot_species_density_map(grids, hex_size, viz_path)
        panels_path = os.path.splitext(output_path)[0] + "_species_density_panels.png"
        plot_species_density_panels(grids, hex_size, panels_path, grid_dpi=20, save_dpi=150)

    print("\nDone.")


if __name__ == "__main__":
    main()
