import json

d = json.load(open('hexdynamic/out35.json'))

print("=== Grid 944 info ===")
g944 = None
for g in d['grids']:
    if g['grid_id'] == 944:
        g944 = g
        break

print(f"Grid 944: q={g944['q']}, r={g944['r']}")
print(f"Fences: {g944.get('fences', {})}")

print("\n=== Map extent ===")
min_q = min(g['q'] for g in d['grids'])
max_q = max(g['q'] for g in d['grids'])
min_r = min(g['r'] for g in d['grids'])
max_r = max(g['r'] for g in d['grids'])
print(f"q range: {min_q} to {max_q}")
print(f"r range: {min_r} to {max_r}")

print("\n=== Corner grids ===")
for g in d['grids']:
    if g['q'] == min_q and g['r'] == min_r:
        print(f"Top-left (q={min_q}, r={min_r}): Grid {g['grid_id']}, fences={g.get('fences', {})}")
    if g['q'] == max_q and g['r'] == min_r:
        print(f"Top-right (q={max_q}, r={min_r}): Grid {g['grid_id']}, fences={g.get('fences', {})}")
    if g['q'] == min_q and g['r'] == max_r:
        print(f"Bottom-left (q={min_q}, r={max_r}): Grid {g['grid_id']}, fences={g.get('fences', {})}")
    if g['q'] == max_q and g['r'] == max_r:
        print(f"Bottom-right (q={max_q}, r={max_r}): Grid {g['grid_id']}, fences={g.get('fences', {})}")

print("\n=== Grid 944 position analysis ===")
print(f"Grid 944 has r={g944['r']}, min_r={min_r}, max_r={max_r}")
if g944['r'] == min_r:
    print("Grid 944 is at the TOP of the map (minimum r)")
elif g944['r'] == max_r:
    print("Grid 944 is at the BOTTOM of the map (maximum r)")
else:
    print("Grid 944 is in the middle of the map")
