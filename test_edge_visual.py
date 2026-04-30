import json
import math
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon

d = json.load(open('hexdynamic/out36.json'))

g944 = None
for g in d['grids']:
    if g['grid_id'] == 944:
        g944 = g
        break

g0 = None
for g in d['grids']:
    if g['grid_id'] == 0:
        g0 = g
        break

hex_size = 200.0

def hex_corners(cx, cy, size):
    pts = []
    for i in range(6):
        a = math.pi / 3 * i + math.pi / 6
        pts.append((cx + size * math.cos(a), cy + size * math.sin(a)))
    return pts

# Draw grid 944
fig, ax = plt.subplots(figsize=(10, 10))
cx, cy = (0, 0)
pts_944 = hex_corners(cx, cy, hex_size)
poly_944 = Polygon(pts_944, closed=True, facecolor='lightgreen', edgecolor='black', linewidth=0.5)
ax.add_patch(poly_944)

# Mark each corner
for i in range(6):
    ax.text(pts_944[i][0], pts_944[i][1], f"C{i}", ha='center', va='center', fontsize=14, color='darkred')

# Mark dir_to_corners (original way)
dir_to_corners_orig = {
    0: (0, 5),  # East: corners 0 and 5
    1: (1, 0),  # Northeast: corners 1 and 0
    2: (2, 1),  # Northwest: corners 2 and 1
    3: (3, 2),  # West: corners 3 and 2
    4: (4, 3),  # Southwest: corners 4 and 3
    5: (5, 4),  # Southeast: corners 5 and 4
}

edge_colors = ['red', 'blue', 'green', 'purple', 'orange', 'cyan']
dir_names = ['East', 'Northeast', 'Northwest', 'West', 'Southwest', 'Southeast']
for dir, (ci, cj) in [(d, *vs) for d, vs in dir_to_corners_orig.items()]:
    ax.plot([pts_944[ci][0], pts_944[cj][0]], [pts_944[ci][1], pts_944[cj][1]], color=edge_colors[dir], linewidth=6, alpha=0.7)
    mid_x = (pts_944[ci][0] + pts_944[cj][0]) / 2
    mid_y = (pts_944[ci][1] + pts_944[cj][1]) / 2
    ax.text(mid_x, mid_y, f"dir{dir}: {dir_names[dir]}", color=edge_colors[dir], fontsize=12, bbox=dict(facecolor='white', alpha=0.7))

plt.axis('equal')
plt.title("Original: Direction Edge Mapping (Grid 944 example)")
plt.savefig('d:\\code\\immc2026-BAI\\hexdynamic\\edge_mapping_vis.png', dpi=150, bbox_inches='tight')
print("Saved edge mapping visual")