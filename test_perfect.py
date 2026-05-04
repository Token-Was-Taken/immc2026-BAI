import json

d = json.load(open('hexdynamic/out35.json'))

g944 = None
for g in d['grids']:
    if g['grid_id'] == 944:
        g944 = g
        break

print("=== Perfect Match: 886 at Northeast (1), boundary edges 2,3,4,5 ===")
q, r = g944['q'], g944['r']
pos_to_gid = {(g['q'], g['r']): g['grid_id'] for g in d['grids']}

# 用户需要：
# - Northeast (1) 是 886 ✓
# - boundary_edge_list 是 2,3,4,5 ✓
# 这意味着：
# - Directions 2, 3, 4, 5 are boundaries (no neighbor)
# - Directions 0, 1 have neighbors (East and Northeast are not boundaries)

perfect_directions = [
    (1, 0, "East", 0),           # should have neighbor (946)
    (0, 1, "Northeast", 1),      # should have neighbor (886)
    (-1, 1, "Northwest", 2),     # boundary (no neighbor)
    (-1, 0, "West", 3),          # boundary
    (0, -1, "Southwest", 4),     # boundary
    (1, -1, "Southeast", 5),     # boundary
]

print(f"{'idx':<4} {'name':<15} {'dq':<4} {'dr':<4} {'neighbor':<10} {'status':<10}")
print("-" * 60)
boundary_edges = []
for dq, dr, name, idx in perfect_directions:
    nq, nr = q + dq, r + dr
    has_neighbor = (nq, nr) in pos_to_gid
    neighbor = pos_to_gid.get((nq, nr), "None")
    status = "BOUNDARY" if not has_neighbor else "HAS NEIGHBOR"
    print(f"{idx:<4} {name:<15} {dq:<+4} {dr:<+4} {neighbor:<10} {status:<10}")
    if neighbor == 886:
        print(f"    ★★★ 886 FOUND AT {name}! ★★★")
    if not has_neighbor:
        boundary_edges.append(idx)

print("\n✅ FINAL RESULT:")
print(f"Expected boundary_edge_list: [2, 3, 4, 5]")
print(f"Actual with new mapping:      {boundary_edges}")
