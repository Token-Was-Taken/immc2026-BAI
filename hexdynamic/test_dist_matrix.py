import time, json, sys
sys.path.insert(0, '.')
from grid_model import HexGridModel
from data_loader import GridData

data = json.load(open('inputs/big.json', encoding='utf-8'))
grids_data = data['grids']
grids = []
for g in grids_data:
    gd = GridData(
        grid_id=g['grid_id'],
        q=g['q'],
        r=g['r'],
        terrain_type=g.get('terrain_type', 'Unknown'),
        risk=0.0,
        temporal_factor=1.0
    )
    grids.append(gd)

print(f'Grids: {len(grids)}')

t0 = time.time()
gm = HexGridModel(grids)
t1 = time.time()
print(f'HexGridModel init (adjacency only): {t1-t0:.1f}s')

has = gm.has_distance_matrix()
t2 = time.time()
print(f'has_distance_matrix={has}, time={t2-t1:.1f}s')

if has:
    dm = gm.distance_matrix
    t3 = time.time()
    print(f'distance_matrix shape={dm.shape}, dtype={dm.dtype}, size={dm.nbytes/1024**3:.2f} GiB, time={t3-t2:.1f}s')
