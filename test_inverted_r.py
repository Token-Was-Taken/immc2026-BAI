import json

d = json.load(open('hexdynamic/out35.json'))

g944 = None
for g in d['grids']:
    if g['grid_id'] == 944:
        g944 = g
        break

print("=== Original Directions ===")
directions_orig = [
    (1, 0, "East", 0),
    (1, -1, "Northeast", 1),
    (0, -1, "Northwest", 2),
    (-1, 0, "West", 3),
    (-1, 1, "Southwest", 4),
    (0, 1, "Southeast", 5),
]

q, r = g944['q'], g944['r']
pos_to_gid = {(g['q'], g['r']): g['grid_id'] for g in d['grids']}

for dq, dr, name, idx in directions_orig:
    nq, nr = q + dq, r + dr
    has_neighbor = (nq, nr) in pos_to_gid
    neighbor = pos_to_gid.get((nq, nr), "None")
    print(f"  {idx}: {name:12} (dq={dq:+}, dr={dr:+}) -> neighbor={neighbor}")

print("\n=== With Inverted r (dr = -dr) ===")
directions_inv = [
    (1, 0, "East", 0),
    (1, 1, "Northeast", 1),
    (0, 1, "Northwest", 2),
    (-1, 0, "West", 3),
    (-1, -1, "Southwest", 4),
    (0, -1, "Southeast", 5),
]

for dq, dr, name, idx in directions_inv:
    nq, nr = q + dq, r + dr
    has_neighbor = (nq, nr) in pos_to_gid
    neighbor = pos_to_gid.get((nq, nr), "None")
    print(f"  {idx}: {name:12} (dq={dq:+}, dr={dr:+}) -> neighbor={neighbor}")
    if neighbor == 886:
        print(f"    ★★★ Found 886 at Northeast! ★★★")
