import json

with open('hexdynamic/out1.json') as f:
    data = json.load(f)

all_fences = []
for g in data['grids']:
    fences = g.get('fences', {})
    if fences.get('fence_count', 0) > 0:
        all_fences.append({
            'grid_id': g['grid_id'],
            'boundary_edges': fences.get('boundary_edge_list', [])
        })

print(f'Total grids with fences: {len(all_fences)}')
for f in all_fences[:10]:
    print(f"  Grid {f['grid_id']}: edges {f['boundary_edges']}")