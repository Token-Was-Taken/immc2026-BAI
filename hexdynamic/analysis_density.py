import json
from collections import deque, defaultdict

with open(r"c:\immc2026-BAI\immc2026-BAI\hexdynamic\inputs\big4_etosha.json", "r", encoding="utf-8") as f:
    data = json.load(f)

grids = data["grids"]
print(f"总网格数: {len(grids)}")

grid_map = {}
for g in grids:
    grid_map[(g["q"], g["r"])] = g

DIRECTIONS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1)]

def get_neighbors(q, r):
    neighbors = []
    for dq, dr in DIRECTIONS:
        nq, nr = q + dq, r + dr
        if (nq, nr) in grid_map:
            neighbors.append((nq, nr))
    return neighbors

water_holes = [(q, r) for (q, r), g in grid_map.items() if g["terrain_type"] == "WaterHole"]
salt_marshes = [(q, r) for (q, r), g in grid_map.items() if g["terrain_type"] == "SaltMarsh"]
print(f"WaterHole网格数: {len(water_holes)}")
print(f"SaltMarsh网格数: {len(salt_marshes)}")

def bfs_multi_source(sources):
    dist = {}
    queue = deque()
    for s in sources:
        dist[s] = 0
        queue.append(s)
    while queue:
        q, r = queue.popleft()
        for nq, nr in get_neighbors(q, r):
            if (nq, nr) not in dist:
                dist[(nq, nr)] = dist[(q, r)] + 1
                queue.append((nq, nr))
    return dist

water_dist = bfs_multi_source(water_holes)
salt_dist = bfs_multi_source(salt_marshes)

print("\n" + "="*70)
print("1. BFS距离统计概览")
print("="*70)
water_dists = [water_dist[k] for k in grid_map if k in water_dist]
salt_dists = [salt_dist[k] for k in grid_map if k in salt_dist]
print(f"到WaterHole最短距离: min={min(water_dists)}, max={max(water_dists)}, mean={sum(water_dists)/len(water_dists):.2f}")
print(f"到SaltMarsh最短距离: min={min(salt_dists)}, max={max(salt_dists)}, mean={sum(salt_dists)/len(salt_dists):.2f}")

zone_a = []
zone_b = []
zone_c = []
for (q, r), g in grid_map.items():
    if g["terrain_type"] == "SaltMarsh":
        zone_a.append((q, r))
    elif water_dist.get((q, r), 999) <= 15:
        zone_b.append((q, r))
    else:
        zone_c.append((q, r))

print("\n" + "="*70)
print("2. Zone分类统计")
print("="*70)
print(f"Zone A (SaltMarsh): {len(zone_a)} 网格")
print(f"Zone B (water_dist<=15, 非SaltMarsh): {len(zone_b)} 网格")
print(f"Zone C (其余): {len(zone_c)} 网格")
total = len(grids)
print(f"占比: A={len(zone_a)/total*100:.1f}%, B={len(zone_b)/total*100:.1f}%, C={len(zone_c)/total*100:.1f}%")

def zone_stats(zone_cells, zone_name):
    print(f"\n--- {zone_name} 物种密度分布 ---")
    for sp in ["rhino", "elephant", "bird"]:
        present = sum(1 for (q, r) in zone_cells if grid_map[(q, r)]["species_densities"][sp] > 0)
        ratio = present / len(zone_cells) * 100 if zone_cells else 0
        print(f"  {sp}: 有密度网格数={present}, 占比={ratio:.1f}%")

zone_stats(zone_a, "Zone A")
zone_stats(zone_b, "Zone B")
zone_stats(zone_c, "Zone C")

DIST_BINS = [(0, 3), (3, 6), (6, 10), (10, 15), (15, 25), (25, float('inf'))]
BIN_LABELS = ["0-3", "3-6", "6-10", "10-15", "15-25", "25+"]

def dist_bin_stats(dist_map, label):
    print(f"\n{'='*70}")
    print(f"3. 按到{label}的距离分段统计")
    print("="*70)
    header = f"{'距离段':<10}"
    for sp in ["rhino", "elephant", "bird"]:
        header += f"{'总网格':>8} {sp+'有密度':>10} {sp+'占比':>8}"
    print(header)
    print("-" * len(header))
    for (lo, hi), lbl in zip(DIST_BINS, BIN_LABELS):
        cells = [(q, r) for (q, r) in grid_map if lo <= dist_map.get((q, r), 999) < hi]
        n = len(cells)
        row = f"{lbl:<10}"
        for sp in ["rhino", "elephant", "bird"]:
            present = sum(1 for (q, r) in cells if grid_map[(q, r)]["species_densities"][sp] > 0)
            ratio = present / n * 100 if n else 0
            row += f"{n:>8} {present:>10} {ratio:>7.1f}%"
        print(row)

dist_bin_stats(salt_dist, "SaltMarsh")
dist_bin_stats(water_dist, "WaterHole")

print(f"\n{'='*70}")
print("4. 各物种密度范围和均值")
print("="*70)
for sp in ["rhino", "elephant", "bird"]:
    vals = [grid_map[(q, r)]["species_densities"][sp] for (q, r) in grid_map]
    positive = [v for v in vals if v > 0]
    print(f"\n--- {sp} ---")
    print(f"  总网格数: {len(vals)}")
    print(f"  有密度网格数: {len(positive)}")
    print(f"  有密度占比: {len(positive)/len(vals)*100:.1f}%")
    if positive:
        print(f"  密度范围: [{min(positive):.4f}, {max(positive):.4f}]")
        print(f"  密度均值(仅>0): {sum(positive)/len(positive):.4f}")
        print(f"  密度均值(全部): {sum(vals)/len(vals):.4f}")
    else:
        print(f"  无正密度网格")

print(f"\n{'='*70}")
print("5. 多物种热点统计")
print("="*70)
rhino_set = set((q, r) for (q, r), g in grid_map.items() if g["species_densities"]["rhino"] > 0)
elephant_set = set((q, r) for (q, r), g in grid_map.items() if g["species_densities"]["elephant"] > 0)
bird_set = set((q, r) for (q, r), g in grid_map.items() if g["species_densities"]["bird"] > 0)

re = rhino_set & elephant_set
rb = rhino_set & bird_set
eb = elephant_set & bird_set
all3 = rhino_set & elephant_set & bird_set

print(f"rhino有密度网格数: {len(rhino_set)}")
print(f"elephant有密度网格数: {len(elephant_set)}")
print(f"bird有密度网格数: {len(bird_set)}")
print(f"rhino+elephant共存: {len(re)} 网格")
print(f"rhino+bird共存: {len(rb)} 网格")
print(f"elephant+bird共存: {len(eb)} 网格")
print(f"三物种共存: {len(all3)} 网格")

print(f"\n{'='*70}")
print("6. Zone B中各物种分布详情")
print("="*70)
zone_b_set = set(zone_b)
print(f"Zone B总网格数: {len(zone_b)}")
for sp in ["rhino", "elephant", "bird"]:
    present = [grid_map[(q, r)]["species_densities"][sp] for (q, r) in zone_b if grid_map[(q, r)]["species_densities"][sp] > 0]
    print(f"\n--- Zone B - {sp} ---")
    print(f"  有密度网格数: {len(present)}")
    print(f"  占Zone B比例: {len(present)/len(zone_b)*100:.1f}%")
    if present:
        print(f"  密度范围: [{min(present):.4f}, {max(present):.4f}]")
        print(f"  密度均值: {sum(present)/len(present):.4f}")

print("\n\n===== 分析完成 =====")
