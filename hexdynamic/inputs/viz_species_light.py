"""
轻量版：可视化 big4o_species.json 的物种分布。
- 跳过 5 分钟的 pipeline 优化
- 使用 odd-r offset + pointy-topped 几何（与 visualize_output.py 一致）
- 只画 species_map 一张关键图
"""
import json
import os
import math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Polygon

INPUT  = r'e:\code\immc2026-BAI\hexdynamic\inputs\big4o_species.json'
OUT_DIR = r'e:\code\immc2026-BAI\hexdynamic\figures\inputs_viz'
os.makedirs(OUT_DIR, exist_ok=True)

with open(INPUT, 'r', encoding='utf-8') as f:
    data = json.load(f)

grids = data['grids']
species_map = {g['grid_id']: g['species_densities'] for g in grids}
hex_size = float(grids[0].get('hex_size', 20))

# 地形配色
TERRAIN_COLORS = {
    'DenseGrass':  '#4ade80',  # 绿 - 森林密集区
    'SparseGrass': '#ef4444',  # 红 - 森林稀疏区
    'WaterHole':   '#3b82f6',  # 蓝 - 水坑
    'SaltMarsh':   '#eab308',  # 黄 - 盐沼
    'Road':        '#a855f7',  # 紫 - 主路
}

# 物种样式
SPECIES_STYLE = {
    'rhino':    {'marker': 'o', 'color': '#1f2937', 'label': 'Black Rhino'},
    'elephant': {'marker': 's', 'color': '#92400e', 'label': 'Elephant'},
    'bird':     {'marker': '^', 'color': '#dc2626', 'label': 'Bird'},
}

# 与 visualize_output.py 一致的 odd-r offset + pointy-topped 几何
def grid_center(q, r, size):
    col = q + (r // 2)
    x = size * math.sqrt(3) * (col + 0.5 * (r & 1))
    y = size * 1.5 * r
    return x, y


def hex_corners(cx, cy, size):
    pts = []
    for i in range(6):
        a = math.pi / 3 * i + math.pi / 6  # pointy-topped
        pts.append((cx + size * math.cos(a), cy + size * math.sin(a)))
    return pts


# 计算画布范围
print("[1/3] 计算坐标 ...")
xs = [grid_center(g['q'], g['r'], hex_size)[0] for g in grids]
ys = [grid_center(g['q'], g['r'], hex_size)[1] for g in grids]
x_min, x_max = min(xs), max(xs)
y_min, y_max = min(ys), max(ys)
margin = hex_size * 1.5
fig_w = (x_max - x_min) / 100 + 8
fig_h = (y_max - y_min) / 100 + 6
fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=80)

# 1) 画所有六边形地形背景 (pointy-topped)
print("[2/3] 绘制地形背景 ...")
for g in grids:
    cx, cy = grid_center(g['q'], g['r'], hex_size)
    color = TERRAIN_COLORS.get(g['terrain_type'], '#ccc')
    hex_poly = Polygon(hex_corners(cx, cy, hex_size * 0.95), closed=True,
                       facecolor=color, edgecolor='black',
                       linewidth=0.05, alpha=0.4)
    ax.add_patch(hex_poly)

# 2) 画物种点
print("[3/3] 绘制物种密度点 ...")
all_species = ['rhino', 'elephant', 'bird']
species_pts = {sp: {'x': [], 'y': [], 's': []} for sp in all_species}

for g in grids:
    sd = species_map.get(g['grid_id'], {})
    cx, cy = grid_center(g['q'], g['r'], hex_size)
    for sp in all_species:
        d = sd.get(sp, 0)
        if d > 0:
            species_pts[sp]['x'].append(cx)
            species_pts[sp]['y'].append(cy)
            species_pts[sp]['s'].append(max(8, 60 * d))

for sp, pts in species_pts.items():
    style = SPECIES_STYLE[sp]
    ax.scatter(pts['x'], pts['y'], marker=style['marker'], c=style['color'],
               s=pts['s'], edgecolors='black', linewidths=0.3, alpha=0.8, zorder=5,
               label=style['label'])

# 3) 美化
ax.set_xlim(x_min - margin, x_max + margin)
ax.set_ylim(y_min - margin, y_max + margin)
ax.set_aspect('equal')
ax.set_title('Species Density Map (Etosha, 24427 hexes, pointy-topped)',
             fontsize=14, fontweight='bold')
ax.set_xlabel('x (odd-r offset col)')
ax.set_ylabel('y (row * 30)')
ax.grid(True, alpha=0.2)

# 4) 图例
terrain_handles = [mpatches.Patch(facecolor=c, edgecolor='black', linewidth=0.5,
                                   alpha=0.5, label=t)
                   for t, c in TERRAIN_COLORS.items()]
species_handles = [plt.Line2D([0], [0], marker=SPECIES_STYLE[sp]['marker'], color='w',
                              markerfacecolor=SPECIES_STYLE[sp]['color'],
                              markeredgecolor='black', markersize=10,
                              label=SPECIES_STYLE[sp]['label'])
                   for sp in all_species]

leg1 = ax.legend(handles=terrain_handles, title='Terrain', loc='upper left',
                 bbox_to_anchor=(1.01, 1.0), fontsize=9, title_fontsize=10)
ax.add_artist(leg1)
ax.legend(handles=species_handles, title='Species (size ∝ density)', loc='upper left',
          bbox_to_anchor=(1.01, 0.6), fontsize=9, title_fontsize=10)

# 5) 统计文本
from collections import defaultdict
sums = defaultdict(float)
counts = defaultdict(int)
for sd in species_map.values():
    for sp, d in sd.items():
        if d > 0:
            sums[sp] += d
            counts[sp] += 1
stats = "Density coverage (grids with d>0):\n"
for sp in all_species:
    stats += f"  {sp:9s}: {counts[sp]:>5d} grids, mean={sums[sp]/max(1, counts[sp]):.2f}\n"
stats += f"\nTotal grids: {len(grids)}"
ax.text(0.02, 0.02, stats, transform=ax.transAxes, fontsize=8.5, family='monospace',
        verticalalignment='bottom',
        bbox=dict(boxstyle='round,pad=0.4', facecolor='white', edgecolor='gray', alpha=0.9))

plt.tight_layout()
out_png = os.path.join(OUT_DIR, 'species_map.png')
plt.savefig(out_png, dpi=100, bbox_inches='tight')
plt.close(fig)
print(f"\n[OK] 已保存: {out_png}")
print(f"     大小: {os.path.getsize(out_png)/1024:.1f} KB")
