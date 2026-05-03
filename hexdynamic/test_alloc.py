import json, numpy as np, time, sys
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
del data, grids_data

t0 = time.time()
gm = HexGridModel(grids)
t1 = time.time()
print(f'HexGridModel init: {t1-t0:.1f}s')

n = len(grids)
print(f'Trying to allocate {n}x{n} float32 = {n*n*4/1024**3:.2f} GiB...')
try:
    m = np.empty((n, n), dtype=np.float32)
    print(f'Allocated: {m.nbytes/1024**3:.2f} GiB')
    del m
    print('Direct allocation OK')
except MemoryError:
    print('Direct allocation FAILED')

print('Trying via has_distance_matrix...')
has = gm.has_distance_matrix()
t2 = time.time()
print(f'has_distance_matrix={has}, time={t2-t1:.1f}s')
