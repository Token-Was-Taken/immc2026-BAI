import json
import os

# Check output/results.json or out36.json
path1 = os.path.join('hexdynamic', 'output', 'results.json')
path2 = os.path.join('hexdynamic', 'out36.json')
path3 = os.path.join('hexdynamic', 'out35.json')

if os.path.exists(path1):
    d = json.load(open(path1))
    print(f"Loaded {path1}")
    print("Grids key in d:", list(d.keys()))
    g944 = None
    for g in d.get('grids', []):
        if g.get('grid_id') == 944:
            g944 = g
    if g944:
        print("\ngrid944 found!")
        print(f"q={g944['q']}, r={g944['r']}")
        if 'fences' in g944:
            print(f"boundary_edge_list: {g944['fences'].get('boundary_edge_list', 'N/A')}")

elif os.path.exists(path2):
    print(f"Checking {path2}")
    d = json.load(open(path2))
    g944 = None
    for g in d['grids']:
        if g['grid_id'] == 944:
            g944 = g
    print(f"grid944 boundary_edge_list: {g944['fences']['boundary_edge_list']}")

print("\nChecking generated files in hexdynamic/output:")
for f in os.listdir('hexdynamic/output'):
    print(f" - {f}")