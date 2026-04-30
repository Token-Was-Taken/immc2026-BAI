import json

d = json.load(open('hexdynamic/out35.json'))

# Find grid 944
g944 = None
for g in d['grids']:
    if g['grid_id'] == 944:
        g944 = g
        break

print(f"Grid 944: q={g944['q']}, r={g944['r']}")
print(f"Current boundary_edge_list: {g944.get('fences', {}).get('boundary_edge_list', [])}")

# Check neighbors
directions = [
    (1, 0, "East"),
    (1, -1, "Northeast"),
    (0, -1, "Northwest"),
    (-1, 0, "West"),
    (-1, 1, "Southwest"),
    (0, 1, "Southeast")
]

q, r = g944['q'], g944['r']
print("\nNeighbor check:")
boundary_dirs = []
for dir_idx, (dq, dr, name) in enumerate(directions):
    nq, nr = q + dq, r + dr
    exists = any(g['q'] == nq and g['r'] == nr for g in d['grids'])
    is_boundary = not exists
    if is_boundary:
        boundary_dirs.append(dir_idx)
    print(f"  Direction {dir_idx} ({name}): q={nq}, r={nr} -> {'BOUNDARY' if is_boundary else 'has neighbor'}")

print(f"\nExpected boundary_edge_list: {boundary_dirs}")
print(f"Actual boundary_edge_list: {g944.get('fences', {}).get('boundary_edge_list', [])}")

# Based on the screenshot, the boundary edges should be:
# nw(2), w(3), sw(4), se(5)
print("\nBased on screenshot, expected boundary edges: [2, 3, 4, 5]")
print("This means directions 0(East) and 1(Northeast) should have neighbors")
print("Let's verify:")
print(f"  Direction 0 (East): q={q+1}, r={r} -> {'BOUNDARY' if not any(g['q']==q+1 and g['r']==r for g in d['grids']) else 'has neighbor'}")
print(f"  Direction 1 (Northeast): q={q+1}, r={r-1} -> {'BOUNDARY' if not any(g['q']==q+1 and g['r']==r-1 for g in d['grids']) else 'has neighbor'}")
