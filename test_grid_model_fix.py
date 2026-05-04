import json
import sys
import os

sys.path.insert(0, os.path.abspath('hexdynamic'))

from grid_model import HexGridModel

# Load out35.json
data = json.load(open('hexdynamic/out35.json'))
grids_data = data['grids']

# Build HexGridModel
model = HexGridModel(grids_data)

# Get grid944
g944 = model.get_grid(944)

print("grid944: q={}, r={}".format(g944.q, g944.r))
boundary_edges = model.get_boundary_edges_for_grid(944)
print("boundary_edges (grid_id, direction): {}".format(boundary_edges))
dir_list = [dir_idx for gid, dir_idx in boundary_edges]
print("boundary_edge_list: {}".format(dir_list))

print("\n--- Directions explanation ---")
directions = [
    (1, 0, 0, "East (0)"),
    (0, 1, 1, "Northeast (1)"),
    (-1, 1, 2, "Northwest (2)"),
    (-1, 0, 3, "West (3)"),
    (0, -1, 4, "Southwest (4)"),
    (1, -1,5, "Southeast (5)"),
]

print("Checking neighbor existence in each direction for 944:")
pos_to_grid = {(g.q, g.r): g for g in model.grids}
for dq, dr, dir_idx, desc in directions:
    nq = g944.q + dq
    nr = g944.r + dr
    has_neighbor = (nq, nr) in pos_to_grid
    neighbor_gid = pos_to_grid[(nq, nr)].grid_id if has_neighbor else None
    print(f"  {desc}: (q={nq}, r={nr}) has neighbor? {has_neighbor} (gid: {neighbor_gid})")