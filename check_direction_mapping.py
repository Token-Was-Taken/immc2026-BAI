import json
import math

d = json.load(open('hexdynamic/out35.json'))

def grid_center(q, r, size):
    col = q + (r // 2)
    x = size * math.sqrt(3) * (col + 0.5 * (r & 1))
    y = size * 1.5 * r
    return x, y

hex_size = 200

print("=== Grid 944 Information ===")
g944 = None
for g in d['grids']:
    if g['grid_id'] == 944:
        g944 = g
        break

print(f"grid_id: {g944['grid_id']}, q: {g944['q']}, r: {g944['r']}")
print(f"boundary_edge_list: {g944.get('fences', {}).get('boundary_edge_list', [])}")

# 打印Grid 944周围的网格
print("\n=== Grids Near Grid 944 ===")
print(f"{'grid_id':<8} {'q':<4} {'r':<4} {'x':<10} {'y':<10} {'distance':<10}")
print("-" * 60)

cx944, cy944 = grid_center(g944['q'], g944['r'], hex_size)

near_grids = []
for g in d['grids']:
    if abs(g['q'] - g944['q']) <= 2 and abs(g['r'] - g944['r']) <= 2:
        x, y = grid_center(g['q'], g['r'], hex_size)
        dist = math.sqrt((x - cx944)**2 + (y - cy944)**2)
        near_grids.append((g['grid_id'], g['q'], g['r'], x, y, dist))

# 按距离排序
near_grids.sort(key=lambda x: x[5])
for gid, q, r, x, y, dist in near_grids:
    print(f"{gid:<8} {q:<4} {r:<4} {x:<10.1f} {y:<10.1f} {dist:<10.1f}")

# 尝试不同的方向映射
print("\n=== Testing Different Direction Mappings ===")
directions1 = [  # 原始定义
    (1, 0, "East"),
    (1, -1, "Northeast"),
    (0, -1, "Northwest"),
    (-1, 0, "West"),
    (-1, 1, "Southwest"),
    (0, 1, "Southeast"),
]

directions2 = [  # 旋转后的可能定义
    (0, 1, "Southeast"),
    (1, 1, "East"),
    (1, 0, "Northeast"),
    (0, -1, "Northwest"),
    (-1, -1, "West"),
    (-1, 0, "Southwest"),
]

directions3 = [  # 反转r方向
    (1, 0, "East"),
    (1, 1, "Northeast"),
    (0, 1, "Northwest"),
    (-1, 0, "West"),
    (-1, -1, "Southwest"),
    (0, -1, "Southeast"),
]

q, r = g944['q'], g944['r']
pos_to_gid = {(g['q'], g['r']): g['grid_id'] for g in d['grids']}

print("\n--- Original Directions ---")
for dir_idx, (dq, dr, name) in enumerate(directions1):
    nq, nr = q + dq, r + dr
    has_neighbor = (nq, nr) in pos_to_gid
    neighbor_gid = pos_to_gid.get((nq, nr), "None")
    print(f"  {dir_idx}: {name} (dq={dq}, dr={dr}) -> {neighbor_gid}")

print("\n--- Direction Mapping 2 ---")
for dir_idx, (dq, dr, name) in enumerate(directions2):
    nq, nr = q + dq, r + dr
    has_neighbor = (nq, nr) in pos_to_gid
    neighbor_gid = pos_to_gid.get((nq, nr), "None")
    print(f"  {dir_idx}: {name} (dq={dq}, dr={dr}) -> {neighbor_gid}")

print("\n--- Direction Mapping 3 (Inverted r) ---")
for dir_idx, (dq, dr, name) in enumerate(directions3):
    nq, nr = q + dq, r + dr
    has_neighbor = (nq, nr) in pos_to_gid
    neighbor_gid = pos_to_gid.get((nq, nr), "None")
    print(f"  {dir_idx}: {name} (dq={dq}, dr={dr}) -> {neighbor_gid}")
