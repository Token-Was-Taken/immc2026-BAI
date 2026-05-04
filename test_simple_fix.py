import json
import sys
import os
sys.path.insert(0, os.path.abspath('hexdynamic'))
from data_loader import DataLoader
from grid_model import HexGridModel

# 我们直接从 out35.json 加载 grids data 并构造 Grid 类对象
# 首先看一下 grid_model.py 的 Grid 定义是什么样的！
# 我们看一下 grid_model.py
print("Loading grid_model to get Grid definition...")
with open('hexdynamic/grid_model.py', 'r', encoding='utf-8') as f:
    content = f.read()
print("Grid class defined in grid_model.py! Let's create simple Grid structure!")

# 简单定义一个类，只有需要的属性
class SimpleGrid:
    def __init__(self, grid_id, q, r, terrain_type=None):
        self.grid_id = grid_id
        self.q = q
        self.r = r
        self.terrain_type = terrain_type or 'unknown'

# Load out35.json
data = json.load(open('hexdynamic/out35.json'))
grids_data = data['grids']

# Build our grids
grids = []
for g_data in grids_data:
    grid = SimpleGrid(
        grid_id=g_data['grid_id'],
        q=g_data['q'],
        r=g_data['r'],
        terrain_type=g_data.get('terrain_type')
    )
    grids.append(grid)

print(f"Total grids loaded: {len(grids)}")
pos_to_grid = {(g.q, g.r): g for g in grids}

# Find grid 944
g944 = None
for g in grids:
    if g.grid_id ==944:
        g944 = g
        break

print("\ngrid944: q={}, r={}".format(g944.q, g944.r))
print("Checking which neighbors exist:")

# Now apply our direction mapping!
directions = [
    (1, 0, 0, "East (0)"),
    (0, 1, 1, "Northeast (1)"),
    (-1, 1,2, "Northwest (2)"),
    (-1, 0, 3, "West (3)"),
    (0, -1, 4, "Southwest (4)"),
    (1, -1,5, "Southeast (5)"),
]

boundary_edge_list = []
for dq, dr, dir_idx, desc in directions:
    nq = g944.q + dq
    nr = g944.r + dr
    has_neighbor = (nq, nr) in pos_to_grid
    neighbor_gid = pos_to_grid[(nq, nr)].grid_id if has_neighbor else None
    print(f"  {desc}: neighbor gid {neighbor_gid} (exists: {has_neighbor})")
    if not has_neighbor:
        boundary_edge_list.append(dir_idx)

print("\n--- RESULT ---")
print("Calculated boundary_edge_list for 944: {}".format(boundary_edge_list))
print("Should be [2,3,4,5] as per your description!")