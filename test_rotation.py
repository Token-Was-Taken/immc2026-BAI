import json

d = json.load(open('hexdynamic/out35.json'))

g944 = None
for g in d['grids']:
    if g['grid_id'] == 944:
        g944 = g
        break

print("=== Testing Direction Rotation Schemes ===")
q, r = g944['q'], g944['r']
pos_to_gid = {(g['q'], g['r']): g['grid_id'] for g in d['grids']}

# 测试旋转后的方向序列
# 用户需要：northeast=886，southeast=None
direction_sets = [
    {
        "name": "Rotated 2 steps clockwise",
        "directions": [
            (0, -1, "East", 0),
            (-1, -1, "Northeast", 1),
            (-1, 0, "Northwest", 2),
            (-1, 1, "West", 3),
            (0, 1, "Southwest", 4),
            (1, 1, "Southeast", 5),
        ]
    },
    {
        "name": "Rotated 2 steps counter-clockwise",
        "directions": [
            (0, 1, "East", 0),
            (1, 1, "Northeast", 1),
            (1, 0, "Northwest", 2),
            (1, -1, "West", 3),
            (0, -1, "Southwest", 4),
            (-1, -1, "Southeast", 5),
        ]
    },
    {
        "name": "Completely inverted",
        "directions": [
            (-1, 0, "East", 0),
            (-1, 1, "Northeast", 1),
            (0, 1, "Northwest", 2),
            (1, 0, "West", 3),
            (1, -1, "Southwest", 4),
            (0, -1, "Southeast", 5),
        ]
    },
    {
        "name": "Just swap North/South names",
        "directions": [
            (1, 0, "East", 0),
            (1, 1, "Northeast", 1),
            (0, 1, "Northwest", 2),
            (-1, 0, "West", 3),
            (-1, -1, "Southwest", 4),
            (0, -1, "Southeast", 5),
        ]
    }
]

for scheme in direction_sets:
    print(f"\n--- {scheme['name']} ---")
    boundary_edges = []
    for dq, dr, name, idx in scheme['directions']:
        nq, nr = q + dq, r + dr
        has_neighbor = (nq, nr) in pos_to_gid
        neighbor = pos_to_gid.get((nq, nr), "None")
        print(f"  {idx}: {name:12} (dq={dq:+}, dr={dr:+}) -> neighbor={neighbor}")
        if neighbor == 886:
            print(f"    ★★★ 886 is {name}! ★★★")
        if not has_neighbor:
            boundary_edges.append(idx)
    print(f"  Boundary edges would be: {boundary_edges}")
