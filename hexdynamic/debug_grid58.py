
import json

# Load base1.json to check grid 58
with open('base1.json', 'r') as f:
    data = json.load(f)

print("=== Checking Grid 58 in base1.json ===")

# Find grid 58 in grids
for grid in data['grids']:
    if grid['grid_id'] == 58:
        print(f"Grid 58 details:")
        print(f"  grid_id: {grid['grid_id']}")
        print(f"  original_grid_id: {grid['original_grid_id']}")
        print(f"  q: {grid['q']}")
        print(f"  r: {grid['r']}")
        print(f"  x: {grid['x']}")
        print(f"  y: {grid['y']}")
        print(f"  terrain_type: {grid['terrain_type']}")
        print(f"  hex_size: {grid['hex_size']}")
        break

print("\n=== Checking if grid 58 is in boundary_locations ===")
for loc in data['map_config']['boundary_locations']:
    if loc['x'] == 30 and loc['y'] == 16:
        print(f"Found in boundary_locations:")
        print(f"  x: {loc['x']}, y: {loc['y']}")
        print(f"  original_grid_id: {loc['original_grid_id']}")
        break

print("\n=== Checking neighboring grids ===")
for grid in data['grids']:
    # Check for grid 56 (neighbor of 58)
    if grid['grid_id'] == 56:
        print(f"\nGrid 56 details:")
        print(f"  q: {grid['q']}")
        print(f"  r: {grid['r']}")
        print(f"  x: {grid['x']}")
        print(f"  y: {grid['y']}")
