"""
#Generate species_densities for huge.json using terrain and waterhole proximity.

Rule addition:
- Ensure at least 60% of SparseGrass grids have both rhino=0.0 and elephant=0.0.
"""
import json
import math
import random
from collections import defaultdict
from math import ceil

random.seed(42)

INPUT = r"d:\code\immc2026-BAI\hexdynamic\inputs\huge.json"
VIEWER = r"d:\code\immc2026-BAI\marker\big-viewer.json"
OUTPUT = r"d:\code\immc2026-BAI\hexdynamic\inputs\huge_species.json"

with open(INPUT, "r", encoding="utf-8") as f:
    data = json.load(f)

with open(VIEWER, "r", encoding="utf-8") as f:
    viewer_data = json.load(f)


def jitter(baseline, sigma=0.1):
    """baseline * (1 +/- sigma), clipped to [0, 1]."""
    return round(max(0.0, min(1.0, baseline * (1 + random.uniform(-sigma, sigma)))), 3)


def offset_to_cube(row, col):
    """odd-r offset -> cube coordinates."""
    x = col - (row - (row & 1)) // 2
    z = row
    y = -x - z
    return x, y, z


def hex_distance(r1, c1, r2, c2):
    """Hex distance under odd-r offset."""
    x1, y1, z1 = offset_to_cube(r1, c1)
    x2, y2, z2 = offset_to_cube(r2, c2)
    return max(abs(x1 - x2), abs(y1 - y2), abs(z1 - z2))


def parse_grid_id(gid):
    """'21_166' -> (21, 166)."""
    parts = gid.split("_")
    return int(parts[0]), int(parts[1])


grids = data["grids"]

# 1) Collect waterhole coordinates
waterhole_coords = []
for g in grids:
    if g["terrain_type"] == "WaterHole":
        row, col = parse_grid_id(g["original_grid_id"])
        waterhole_coords.append((row, col))

print(f"WaterHole count: {len(waterhole_coords)}")

# 2) Distance to nearest waterhole for each grid
grid_min_waterhole_dist = {}
for g in grids:
    row, col = parse_grid_id(g["original_grid_id"])
    min_d = min(hex_distance(row, col, wr, wc) for wr, wc in waterhole_coords)
    grid_min_waterhole_dist[g["grid_id"]] = min_d

# 3) Ecotone score from viewer neighbors
viewer_neighbors = {v["gridId"]: v["neighbors"] for v in viewer_data}
ogid_to_terrain = {g["original_grid_id"]: g["terrain_type"] for g in grids}

grid_ecotone_score = {}
for g in grids:
    ogid = g["original_grid_id"]
    neighbors = viewer_neighbors.get(ogid, [])
    neighbor_terrains = set()
    for nid in neighbors:
        nt = ogid_to_terrain.get(nid)
        if nt:
            neighbor_terrains.add(nt)
    neighbor_terrains.add(g["terrain_type"])
    grid_ecotone_score[g["grid_id"]] = min(1.0, (len(neighbor_terrains) - 1) / 3.0)

# 4) SaltMarsh edge distance
saltmarsh_coords = set()
non_saltmarsh_coords = []
for g in grids:
    row, col = parse_grid_id(g["original_grid_id"])
    if g["terrain_type"] == "SaltMarsh":
        saltmarsh_coords.add((row, col))
    else:
        non_saltmarsh_coords.append((row, col))

grid_saltmarsh_edge_dist = {}
for g in grids:
    if g["terrain_type"] == "SaltMarsh":
        row, col = parse_grid_id(g["original_grid_id"])
        min_d = min(hex_distance(row, col, nr, nc) for nr, nc in non_saltmarsh_coords)
        grid_saltmarsh_edge_dist[g["grid_id"]] = min_d


rows = [parse_grid_id(g["original_grid_id"])[0] for g in grids]
cols = [parse_grid_id(g["original_grid_id"])[1] for g in grids]
row_min, row_max = min(rows), max(rows)
col_min, col_max = min(cols), max(cols)


def density_for(g):
    """Generate rhino/elephant/bird density by terrain and context."""
    terrain = g["terrain_type"]
    gid = g["grid_id"]
    ogid = g["original_grid_id"]
    row, col = parse_grid_id(ogid)

    col_norm = (col - col_min) / max(1, col_max - col_min)
    row_norm = (row - row_min) / max(1, row_max - row_min)

    d_water = grid_min_waterhole_dist[gid]
    prox_rhino = math.exp(-d_water / 5.0)
    prox_elephant = math.exp(-d_water / 8.0)
    prox_bird = math.exp(-d_water / 3.0)
    ecotone = grid_ecotone_score[gid]
    sm_edge_d = grid_saltmarsh_edge_dist.get(gid, 0)

    if terrain == "DenseGrass":
        east_boost = 0.6 + 0.4 * col_norm
        rhino_base = 0.7 * east_boost + 0.3 * prox_rhino
    elif terrain == "SparseGrass":
        rhino_base = 0.15 + 0.25 * prox_rhino
    elif terrain == "WaterHole":
        rhino_base = 0.95
    elif terrain == "SaltMarsh":
        rhino_base = 0.02 + 0.03 * prox_rhino
    elif terrain == "Road":
        rhino_base = 0.01 + 0.04 * prox_rhino
    else:
        rhino_base = 0.0

    if terrain == "DenseGrass":
        elephant_base = 0.3 + 0.2 * prox_elephant
    elif terrain == "SparseGrass":
        south_boost = 0.8 + 0.2 * row_norm
        elephant_base = 0.5 * south_boost + 0.3 * prox_elephant
    elif terrain == "WaterHole":
        elephant_base = 0.95
    elif terrain == "SaltMarsh":
        elephant_base = 0.02 + 0.05 * prox_elephant
    elif terrain == "Road":
        elephant_base = 0.01 + 0.04 * prox_elephant
    else:
        elephant_base = 0.0

    if terrain == "DenseGrass":
        bird_base = 0.2 + 0.15 * ecotone + 0.1 * prox_bird
    elif terrain == "SparseGrass":
        bird_base = 0.35 + 0.2 * ecotone + 0.1 * prox_bird
    elif terrain == "WaterHole":
        bird_base = 0.5 + 0.15 * ecotone
    elif terrain == "SaltMarsh":
        edge_factor = math.exp(-sm_edge_d / 3.0)
        bird_base = 0.1 + 0.6 * edge_factor
    elif terrain == "Road":
        bird_base = 0.03 + 0.05 * ecotone
    else:
        bird_base = 0.0

    rhino = jitter(min(1.0, rhino_base), 0.1)
    elephant = jitter(min(1.0, elephant_base), 0.1)
    bird = jitter(min(1.0, bird_base), 0.1)
    return {"rhino": rhino, "elephant": elephant, "bird": bird}


def enforce_sparsegrass_min_no_rhino_elephant(grids, min_ratio=0.6):
    """Ensure at least min_ratio of SparseGrass grids have rhino=0 and elephant=0."""
    sparse = [g for g in grids if g["terrain_type"] == "SparseGrass"]
    if not sparse:
        return 0, 0, 0

    target = ceil(len(sparse) * min_ratio)
    already_zero = [
        g for g in sparse
        if g["species_densities"]["rhino"] == 0.0 and g["species_densities"]["elephant"] == 0.0
    ]
    if len(already_zero) >= target:
        return len(sparse), target, 0

    needed = target - len(already_zero)
    candidates = [
        g for g in sparse
        if not (g["species_densities"]["rhino"] == 0.0 and g["species_densities"]["elephant"] == 0.0)
    ]
    candidates.sort(
        key=lambda g: (
            g["species_densities"]["rhino"] + g["species_densities"]["elephant"],
            g["species_densities"]["rhino"],
            g["species_densities"]["elephant"],
            g["grid_id"],
        )
    )

    changed = 0
    for g in candidates[:needed]:
        g["species_densities"]["rhino"] = 0.0
        g["species_densities"]["elephant"] = 0.0
        changed += 1
    return len(sparse), target, changed


for g in grids:
    g["species_densities"] = density_for(g)

sparse_total, sparse_target, sparse_changed = enforce_sparsegrass_min_no_rhino_elephant(
    grids, min_ratio=0.7
)
if sparse_total > 0:
    sparse_zero = sum(
        1
        for g in grids
        if g["terrain_type"] == "SparseGrass"
        and g["species_densities"]["rhino"] == 0.0
        and g["species_densities"]["elephant"] == 0.0
    )
    sparse_zero_ratio = sparse_zero / sparse_total
    print(
        f"\nSparseGrass zero rhino+elephant enforced: "
        f"{sparse_zero}/{sparse_total} ({sparse_zero_ratio:.1%}), "
        f"target >= {sparse_target}/{sparse_total} (70.0%), adjusted={sparse_changed}"
    )


sums = defaultdict(lambda: defaultdict(float))
counts = defaultdict(int)
for g in grids:
    t = g["terrain_type"]
    counts[t] += 1
    for sp, d in g["species_densities"].items():
        sums[t][sp] += d

print(f'\n{"terrain":<12} {"count":>6} | {"rhino_avg":>9} {"elephant_avg":>12} {"bird_avg":>9}')
print("-" * 60)
for t in ["DenseGrass", "SparseGrass", "WaterHole", "SaltMarsh", "Road"]:
    c = counts[t]
    ra = sums[t]["rhino"] / c if c else 0.0
    ea = sums[t]["elephant"] / c if c else 0.0
    ba = sums[t]["bird"] / c if c else 0.0
    print(f"{t:<12} {c:>6} | {ra:>9.3f} {ea:>12.3f} {ba:>9.3f}")

print("\n--- Waterhole Proximity Effect (SparseGrass) ---")
for dist_range, label in [
    (0, "d=0(waterhole)"),
    (1, "d=1"),
    (2, "d=2"),
    (3, "d=3-5"),
    (6, "d=6+"),
]:
    if dist_range == 0:
        subset = [g for g in grids if g["terrain_type"] == "WaterHole"]
    elif dist_range <= 2:
        subset = [
            g
            for g in grids
            if g["terrain_type"] == "SparseGrass"
            and grid_min_waterhole_dist[g["grid_id"]] == dist_range
        ]
    elif dist_range == 3:
        subset = [
            g
            for g in grids
            if g["terrain_type"] == "SparseGrass"
            and 3 <= grid_min_waterhole_dist[g["grid_id"]] <= 5
        ]
    else:
        subset = [
            g
            for g in grids
            if g["terrain_type"] == "SparseGrass"
            and grid_min_waterhole_dist[g["grid_id"]] >= 6
        ]
    if not subset:
        continue
    ra = sum(g["species_densities"]["rhino"] for g in subset) / len(subset)
    ea = sum(g["species_densities"]["elephant"] for g in subset) / len(subset)
    ba = sum(g["species_densities"]["bird"] for g in subset) / len(subset)
    print(f"  {label:<12} n={len(subset):>5} | rhino={ra:.3f}  elephant={ea:.3f}  bird={ba:.3f}")

with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

import os

print(f"\nSaved: {OUTPUT}")
print(f"File size: {os.path.getsize(OUTPUT) / 1024 / 1024:.2f} MB")
