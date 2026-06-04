import json
from collections import Counter

with open(r'e:\code\immc2026-BAI\hexdynamic\inputs\big4o.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

print(f'grids count: {len(data["grids"])}')
print(f'top-level keys: {list(data.keys())}')
print()

terrain_counter = Counter(g['terrain_type'] for g in data['grids'])
print(f'terrain_type distribution:')
for t, c in sorted(terrain_counter.items(), key=lambda x: -x[1]):
    print(f'  {t}: {c}')

print()
print(f'first grid sample:')
import pprint
pprint.pprint(data['grids'][0])
