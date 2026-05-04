import json

d = json.load(open('hexdynamic/out35.json'))

# Find grid 944
g944 = None
for g in d['grids']:
    if g['grid_id'] == 944:
        g944 = g
        break

if g944:
    print(f"Grid 944: q={g944['q']}, r={g944['r']}")
    print(f"Current boundary_edge_list: {g944.get('fences', {}).get('boundary_edge_list', [])}")

    # Build position lookup
    pos_to_id = {(g['q'], g['r']): g['grid_id'] for g in d['grids']}

    # Check all 6 directions
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
        exists = (nq, nr) in pos_to_id
        is_boundary = not exists
        if is_boundary:
            boundary_dirs.append(dir_idx)
        print(f"  Direction {dir_idx} ({name}): q={nq}, r={nr} -> {'BOUNDARY' if is_boundary else 'has neighbor'}")

    print(f"\nExpected boundary_edge_list: {boundary_dirs}")
    print(f"Actual boundary_edge_list: {g944.get('fences', {}).get('boundary_edge_list', [])}")