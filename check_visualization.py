import json
import math
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon

d = json.load(open('hexdynamic/out35.json'))

def grid_center(q, r, size):
    col = q + (r // 2)
    x = size * math.sqrt(3) * (col + 0.5 * (r & 1))
    y = size * 1.5 * r
    return x, y

def hex_corners(cx, cy, size):
    pts = []
    for i in range(6):
        a = math.pi / 3 * i + math.pi / 6
        pts.append((cx + size * math.cos(a), cy + size * math.sin(a)))
    return pts

hex_size = 200

fig, ax = plt.subplots(figsize=(10, 10))

# 绘制地图上的所有网格
for g in d['grids']:
    cx, cy = grid_center(g['q'], g['r'], hex_size)
    # 选择几个关键点进行高亮
    color = 'lightgreen'
    if g['grid_id'] == 944:
        color = 'yellow'
    if g['grid_id'] == 886:
        color = 'orange'
    if g['grid_id'] == 946:
        color = 'red'
    if g['grid_id'] == 0:
        color = 'blue'
    poly = Polygon(hex_corners(cx, cy, hex_size), closed=True,
                   facecolor=color, edgecolor='black', linewidth=0.5)
    ax.add_patch(poly)
    # 在网格中心显示grid_id
    ax.text(cx, cy, str(g['grid_id']), ha='center', va='center',
            fontsize=8, fontweight='bold', color='black')

# 找到 Grid 944
g944 = None
for g in d['grids']:
    if g['grid_id'] == 944:
        g944 = g
        break

# 绘制方向箭头
if g944:
    cx, cy = grid_center(g944['q'], g944['r'], hex_size)
    
    # 原始方向映射
    directions = [
        (1, 0, "East (0)", 'red'),
        (1, -1, "Northeast (1)", 'orange'),
        (0, -1, "Northwest (2)", 'yellow'),
        (-1, 0, "West (3)", 'green'),
        (-1, 1, "Southwest (4)", 'blue'),
        (0, 1, "Southeast (5)", 'purple'),
    ]
    
    for dq, dr, name, color in directions:
        # 计算箭头指向的点（使用一个小的偏移）
        dx = dq * hex_size * 0.8
        dy = -dr * hex_size * 0.8  # 注意：这里我先试试反转 dy
        
        # 画箭头
        ax.arrow(cx, cy, dx, dy, head_width=hex_size*0.1, head_length=hex_size*0.1,
                 fc=color, ec=color, lw=2)
        # 在箭头旁边标注方向名称
        ax.text(cx + dx*1.2, cy + dy*1.2, name, ha='center', va='center',
                fontsize=10, fontweight='bold', color=color)

# 设置坐标轴范围
xs = [grid_center(g['q'], g['r'], hex_size)[0] for g in d['grids']]
ys = [grid_center(g['q'], g['r'], hex_size)[1] for g in d['grids']]
ax.set_xlim(min(xs) - hex_size, max(xs) + hex_size)
ax.set_ylim(min(ys) - hex_size, max(ys) + hex_size)
ax.set_aspect('equal')
ax.grid(True)
ax.set_title('Grid Direction Mapping (Grid 944 highlighted in yellow)\nRed:946, Orange:886, Blue:0')

plt.savefig('d:\\code\\immc2026-BAI\\hexdynamic\\direction_test.png', dpi=150, bbox_inches='tight')
print("Saved: direction_test.png")
