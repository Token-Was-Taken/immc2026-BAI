import json

# Check original out35.json
d = json.load(open('hexdynamic/out35.json'))
g944 = None
g886 = None
for g in d['grids']:
    if g['grid_id'] == 944:
        g944 = g
    if g['grid_id'] == 886:
        g886 = g

print(f"Grid 944: q={g944['q']}, r={g944['r']}")
print(f"boundary_edge_list: {g944['fences']['boundary_edge_list']}")
print(f"\nGrid 886: q={g886['q']}, r={g886['r']}")

print("\nNow checking all 6 directions for 944 (original mapping):")
directions_original = [
    (1, 0, "East", 0),         #0
    (1, -1, "Northeast", 1),   #1
    (0, -1, "Northwest", 2),   #2
    (-1, 0, "West", 3),        #3
    (-1, 1, "Southwest", 4),   #4
    (0, 1, "Southeast", 5),    #5
]

pos_to_gid = {(g['q'], g['r']): g['grid_id'] for g in d['grids']}
for dq, dr, name, dir_idx in directions_original:
    q = g944['q'] + dq
    r = g944['r'] + dr
    has_neighbor = (q, r) in pos_to_gid
    neighbor_gid = pos_to_gid.get((q, r), None)
    print(f"  dir {dir_idx}: {name} -> (q={q}, r={r}) -> neighbor: {neighbor_gid}")

print("\n--- Now what the user says should be boundary ---")
print("User says boundary edges for 944 are: Northwest (2), West (3), Southwest (4), Southeast (5)")
print("That means dir 0 and dir1 should have neighbors")

print("\nSo what should the direction mapping be for 944?")
print("We know: East has neighbor (946, we can check that),")
print("and Northeast should have neighbor (886)")

g946 = None
for g in d['grids']:
    if g['grid_id'] == 946:
        g946 = g

print(f"\nGrid946: q={g946['q']}, r={g946['r']}")