import json
d = json.load(open('hexdynamic/base1_out2.json'))
print('Top-level keys:', list(d.keys()))

if 'fence_edges' in d:
    print('WARNING: fence_edges still exists')
else:
    print('OK: fence_edges removed')

grids_with_fences = [g for g in d['grids'] if 'fences' in g]
print(f'Grids with fences: {len(grids_with_fences)}')
if grids_with_fences:
    g = grids_with_fences[0]
    print(f"Sample grid fence data: grid_id={g['grid_id']}, fences={g['fences']}")