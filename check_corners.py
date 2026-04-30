import json

with open('hexdynamic/out1.json') as f:
    data = json.load(f)

# 方向定义 (pointy-top hex)
directions = {
    0: "East (东)",
    1: "Northeast (东北)",
    2: "Northwest (西北)",
    3: "West (西)",
    4: "Southwest (西南)",
    5: "Southeast (东南)"
}

# 地图范围
all_x = [g['x'] for g in data['grids']]
all_y = [g['y'] for g in data['grids']]
print(f"地图范围: x=[{min(all_x)}, {max(all_x)}], y=[{min(all_y)}, {max(all_y)}]")
print(f"y={max(all_y)} 是地图顶部，y={min(all_y)} 是地图底部")
print()

# 找到四个角的网格
for g in data['grids']:
    fences = g.get('fences', {})
    if not fences:
        continue
    edges = fences.get('boundary_edge_list', [])

    is_left = g['x'] == min(all_x)
    is_right = g['x'] == max(all_x)
    is_top = g['y'] == max(all_y)
    is_bottom = g['y'] == min(all_y)

    if (is_left and is_top):
        print(f"左上角: Grid {g['grid_id']}: x={g['x']}, y={g['y']}, edges={edges}")
        print(f"  应该有的边界边 (根据方向定义): 1(东北), 2(西北), 3(西)")
        print(f"  实际边界边: {edges}")
        print()
    elif (is_right and is_top):
        print(f"右上角: Grid {g['grid_id']}: x={g['x']}, y={g['y']}, edges={edges}")
    elif (is_left and is_bottom):
        print(f"左下角: Grid {g['grid_id']}: x={g['x']}, y={g['y']}, edges={edges}")
    elif (is_right and is_bottom):
        print(f"右下角: Grid {g['grid_id']}: x={g['x']}, y={g['y']}, edges={edges}")