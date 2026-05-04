import json
import math

d = json.load(open('hexdynamic/out35.json'))

def grid_center(q, r, size):
    col = q + (r // 2)
    x = size * math.sqrt(3) * (col + 0.5 * (r & 1))
    y = size * 1.5 * r
    return x, y

hex_size = 200

# 收集几个关键网格的信息
print("=== Grid Coordinates (Visualization System) ===")
print(f"{'grid_id':<8} {'q':<4} {'r':<4} {'x':<10} {'y':<10}")
print("-" * 50)

# 打印几个角落的网格
corner_grids = []
for g in d['grids']:
    if g['grid_id'] in [0, 944, 1000, 886, 946]:
        x, y = grid_center(g['q'], g['r'], hex_size)
        print(f"{g['grid_id']:<8} {g['q']:<4} {g['r']:<4} {x:<10.1f} {y:<10.1f}")
        corner_grids.append((g['grid_id'], x, y))

# 找到最小和最大的坐标
min_x = min(grid_center(g['q'], g['r'], hex_size)[0] for g in d['grids'])
max_x = max(grid_center(g['q'], g['r'], hex_size)[0] for g in d['grids'])
min_y = min(grid_center(g['q'], g['r'], hex_size)[1] for g in d['grids'])
max_y = max(grid_center(g['q'], g['r'], hex_size)[1] for g in d['grids'])

print("\n=== Map Bounds ===")
print(f"x: {min_x:.1f} to {max_x:.1f}")
print(f"y: {min_y:.1f} to {max_y:.1f}")

print("\n=== Important: In matplotlib, y=0 is at the bottom! ===")
print("So lower y = lower on screen, higher y = higher on screen")
