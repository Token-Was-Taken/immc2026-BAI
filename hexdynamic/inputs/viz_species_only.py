"""
可视化 inputs/big4o_species.json 中的物种分布。
复用 visualize_output.py 中的函数，跳过 pipeline 优化。
"""
import json
import os
import sys
import matplotlib
matplotlib.use("Agg")

sys.path.insert(0, r'e:\code\immc2026-BAI\hexdynamic')
from visualize_output import (
    load_data, plot_species_map, plot_terrain_map,
    plot_risk_heatmap, plot_protection_heatmap,
)

INPUT = r'e:\code\immc2026-BAI\hexdynamic\inputs\big4o_species.json'
OUT_DIR = r'e:\code\immc2026-BAI\hexdynamic\figures\inputs_viz'
os.makedirs(OUT_DIR, exist_ok=True)

# 复用 load_data：把 input JSON 同时当作 output (提供 grids) 和 input (提供 species)
# 实际上 load_data 已经支持：当 input 含 risk_normalized 而 output 不含时会自动交换
# 这里直接手动加载更可控
with open(INPUT, 'r', encoding='utf-8') as f:
    data = json.load(f)

# 1) 构造 species_map: grid_id -> species_densities
species_map = {g['grid_id']: g['species_densities'] for g in data['grids']}

# 2) hex_size
hex_size = float(data['grids'][0].get('hex_size', 20))

# 3) boundary_xy
boundary_xy = []
for item in data.get('map_config', {}).get('boundary_locations', []):
    if isinstance(item, dict):
        boundary_xy.append((item['x'], item['y']))
    else:
        boundary_xy.append(tuple(item))

# 4) grid_dpi
grids = data['grids']
qs = {g['q'] for g in grids}
rs = {g['r'] for g in grids}
max_dim = max(len(qs), len(rs))
grid_dpi = min(80, max(20, int(4000 / max_dim)))
print(f"grids: {len(grids)}, hex_size: {hex_size}, grid_dpi: {grid_dpi}")

# 5) 临时构造 out dict（plot_* 函数读 out['grids']）
out = {'grids': grids}

# 6) 生成 species_map
print("[1/4] plot_species_map ...")
plot_species_map(out, species_map, hex_size, boundary_xy,
                 save_path=os.path.join(OUT_DIR, 'species_map.png'),
                 grid_dpi=grid_dpi, save_dpi=150)

# 7) terrain 背景图（仅供对照）
print("[2/4] plot_terrain_map ...")
plot_terrain_map(out, hex_size, boundary_xy,
                 save_path=os.path.join(OUT_DIR, 'terrain_map.png'),
                 grid_dpi=grid_dpi, save_dpi=150)

# 8) risk heatmap（用 fire_risk 作 risk 代理）
print("[3/4] plot_risk_heatmap ...")
# 注入 risk_normalized 字段（从 fire_risk + terrain_complexity 合成）
import copy
out_risk = copy.deepcopy(out)
for g in out_risk['grids']:
    g['risk_normalized'] = min(1.0, g.get('fire_risk', 0) * 0.7 + g.get('terrain_complexity', 0) * 0.3)
    g['risk_original'] = g['risk_normalized']
try:
    plot_risk_heatmap(out_risk, {g['grid_id']: g for g in out_risk['grids']},
                      hex_size, boundary_xy,
                      save_path=os.path.join(OUT_DIR, 'risk_heatmap.png'),
                      grid_dpi=grid_dpi, save_dpi=150)
except Exception as e:
    print(f"  risk_heatmap skipped: {e}")

print("\n[OK] 输出目录:", OUT_DIR)
for f in sorted(os.listdir(OUT_DIR)):
    p = os.path.join(OUT_DIR, f)
    print(f"  {f}: {os.path.getsize(p)/1024:.1f} KB")
