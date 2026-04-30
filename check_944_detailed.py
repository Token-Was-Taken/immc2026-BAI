import json

d = json.load(open('hexdynamic/out35.json'))

# Find grid 944
g944 = None
for g in d['grids']:
    if g['grid_id'] == 944:
        g944 = g
        break

print(f"Grid 944: q={g944['q']}, r={g944['r']}")

# Check all neighbors around grid 944
print("\nAll grids near (q=1, r=0):")
for g in d['grids']:
    if abs(g['q'] - 1) <= 2 and abs(g['r']) <= 2:
        print(f"  Grid {g['grid_id']}: q={g['q']}, r={g['r']}")

# According to screenshot, boundary edges should be nw(2), w(3), sw(4), se(5)
# This means East(0) and Northeast(1) should have neighbors
print("\nBased on screenshot:")
print("  Direction 0 (East): should have neighbor at (2, 0)")
print("  Direction 1 (Northeast): should have neighbor at (2, -1)")
print("  Direction 2 (Northwest): BOUNDARY at (1, -1)")
print("  Direction 3 (West): BOUNDARY at (0, 0)")
print("  Direction 4 (Southwest): BOUNDARY at (0, 1)")
print("  Direction 5 (Southeast): BOUNDARY at (1, 1)")

print("\nActual check:")
directions = [
    (1, 0, "East"),
    (1, -1, "Northeast"),
    (0, -1, "Northwest"),
    (-1, 0, "West"),
    (-1, 1, "Southwest"),
    (0, 1, "Southeast")
]

q, r = g944['q'], g944['r']
for dir_idx, (dq, dr, name) in enumerate(directions):
    nq, nr = q + dq, r + dr
    exists = any(g['q'] == nq and g['r'] == nr for g in d['grids'])
    print(f"  Direction {dir_idx} ({name}): q={nq}, r={nr} -> {'BOUNDARY' if not exists else 'has neighbor'}")
