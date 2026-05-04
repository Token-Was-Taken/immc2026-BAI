import json

d = json.load(open('hexdynamic/out36.json'))

g944 = None
for g in d['grids']:
    if g['grid_id'] == 944:
        g944 = g
        break

print(f"Grid 944: q={g944['q']}, r={g944['r']}")
print(f"Current boundary_edge_list: {g944.get('fences', {}).get('boundary_edge_list', [])}")

# Check neighbors with new direction mapping
directions = [
    (1, 0, "East", 0),
    (0, 1, "Northeast", 1),
    (-1, 1, "Northwest", 2),
    (-1, 0, "West", 3),
    (0, -1, "Southwest", 4),
    (1, -1, "Southeast", 5)
]

q, r = g944['q'], g944['r']
print("\nNeighbor check:")
boundary_dirs = []
for dir_idx, (dq, dr, name) in enumerate([t[:3] for t in directions]):
    nq, nr = q + dq, r + dr
    exists = any(x['q'] == nq and x['r'] == nr for x in d['grids'])
    if not exists:
        boundary_dirs.append(dir_idx)
    neighbor_id = "None"
    for x in d['grids']:
        if x['q'] == nq and x['r'] == nr:
            neighbor_id = x['grid_id']
            break
    print(f"  Direction {dir_idx} ({name}): q={nq}, r={nr} -> neighbor={neighbor_id} {'→ BOUNDARY' if not exists else ''}")

print(f"\nExpected boundary_edge_list: {boundary_dirs}")
print(f"Actual boundary_edge_list: {g944.get('fences', {}).get('boundary_edge_list', [])}")