import json
import os

script_dir = os.path.dirname(os.path.abspath(__file__))
big_json_path = os.path.join(script_dir, 'inputs', 'big.json')

with open(big_json_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

grids = data.get('grids', [])

print("Map config:")
print(data.get('map_config', {}))

print("\nFirst 5 grids:")
for i, grid in enumerate(grids[:5]):
    print(f"\nGrid {i}:")
    print(f"  original_grid_id: {grid.get('original_grid_id')}")
    print(f"  x: {grid.get('x')}, y: {grid.get('y')}")
    print(f"  q: {grid.get('q')}, r: {grid.get('r')}")

# 找出x和y的范围
xs = []
ys = []
rows = []
cols = []

for grid in grids:
    xs.append(grid.get('x', 0))
    ys.append(grid.get('y', 0))
    original_id = grid.get('original_grid_id', '')
    if '_' in original_id:
        r, c = original_id.split('_', 1)
        rows.append(int(r))
        cols.append(int(c))

print(f"\nX range: {min(xs)} to {max(xs)}")
print(f"Y range: {min(ys)} to {max(ys)}")
print(f"Row range: {min(rows)} to {max(rows)}")
print(f"Col range: {min(cols)} to {max(cols)}")
