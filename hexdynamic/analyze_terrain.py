import json
import os

script_dir = os.path.dirname(os.path.abspath(__file__))
big_json_path = os.path.join(script_dir, 'inputs', 'big.json')

with open(big_json_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

grids = data.get('grids', [])
terrain_types = set()

for grid in grids:
    terrain_type = grid.get('terrain_type', '')
    terrain_types.add(terrain_type)

print("Terrain types found in big.json:")
for t in sorted(terrain_types):
    print(f"  - {t}")

# 统计每种地形类型的数量
from collections import Counter
terrain_counter = Counter(g.get('terrain_type', '') for g in grids)
print("\nTerrain type counts:")
for t, count in terrain_counter.most_common():
    print(f"  {t}: {count}")
