
import json
import sys

# First let's check what fences are in out39.json
print("=== Checking out39.json for grid 58 ===")

with open('out39.json', 'r') as f:
    out_data = json.load(f)

found_58 = False
for grid in out_data['grids']:
    if grid['grid_id'] == 58:
        print(f"Grid 58 found!")
        print(f"  Has 'fences' key? {'fences' in grid}")
        if 'fences' in grid:
            print(f"  fence_count: {grid['fences']['fence_count']}")
            print(f"  boundary_edge_list: {grid['fences']['boundary_edge_list']}")
        found_58 = True
        break

if not found_58:
    print("Grid 58 not found in output!")

print("\n=== Checking out39.json for grid 56 (with fence) ===")
found_56 = False
for grid in out_data['grids']:
    if grid['grid_id'] == 56:
        print(f"Grid 56 found!")
        print(f"  Has 'fences' key? {'fences' in grid}")
        if 'fences' in grid:
            print(f"  fence_count: {grid['fences']['fence_count']}")
            print(f"  boundary_edge_list: {grid['fences']['boundary_edge_list']}")
        found_56 = True
        break

print("\n=== Checking fitness history ===")
print(f"Fitness history len: {len(out_data['summary']['fitness_history'])}")
print(f"First 10 fitness: {out_data['summary']['fitness_history'][:10]}")
