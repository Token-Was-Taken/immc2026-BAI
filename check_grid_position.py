import json
with open('hexdynamic/out1.json') as f:
    data = json.load(f)

# 找到 Grid 0
for g in data['grids']:
    if g['grid_id'] == 0:
        print(f"Grid 0: q={g['q']}, r={g['r']}, x={g['x']}, y={g['y']}")
        print(f"边界边方向: {g['fences']['boundary_edge_list']}")
        break

print()
print("x最小的网格 (最左列):")
leftmost = sorted(data['grids'], key=lambda g: g['x'])[:3]
for g in leftmost:
    print(f"  Grid {g['grid_id']}: x={g['x']}, y={g['y']}")

print()
print("y最大的网格 (最上行):")
topmost = sorted(data['grids'], key=lambda g: g['y'], reverse=True)[:3]
for g in topmost:
    print(f"  Grid {g['grid_id']}: x={g['x']}, y={g['y']}")

print()
print("y最小的网格 (最下行):")
bottommost = sorted(data['grids'], key=lambda g: g['y'])[:3]
for g in bottommost:
    print(f"  Grid {g['grid_id']}: x={g['x']}, y={g['y']}")