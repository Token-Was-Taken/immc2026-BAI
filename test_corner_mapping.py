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

hex_size = 200.0

cx, cy = (0, 0)

def hex_corners(cx, cy, size):
    pts = []
    for i in range(6):
        a = math.pi / 3 * i + math.pi / 6
        pts.append((cx + size * math.cos(a), cy + size * math.sin(a)))
    return pts

pts = hex_corners(cx, cy, hex_size)

fig, ax = plt.subplots(figsize=(10, 10))
poly = Polygon(pts, closed=True, facecolor='lightgreen', edgecolor='black', linewidth=0.5)
ax.add_patch(poly)

for i in range(6):
    ax.text(pts[i][0], pts[i][1], f"corner {i}", ha='center', va='center', fontsize=14, color='darkred')

# Original directions we had before fix
# Now let's test dir_to_corners mapping
dir_to_corners_orig = {
    0: (0, 5),  # East: corners 0 and 5
    1: (1, 0),  # Northeast: corners 1 and 0
    2: (2, 1),  # Northwest: corners 2 and 1
    3: (3, 2),  # West: corners 3 and 2
    4: (4, 3),  # Southwest: corners 4 and 3
    5: (5, 4),  # Southeast: corners 5 and 4
}

# New mapping we used
dir_to_corners_new = {
    0: (0, 5), 
    1: (5, 4), 
    2: (4, 3), 
    3: (3, 2), 
    4: (2, 1), 
    5: (1, 0), 
}

# Plot original dir mappings as red
for dir, (i, j) in dir_to_corners_orig.items():
    x0, y0 = pts[i]
    x1, y1 = pts[j]
    ax.plot([x0, x1], [y0, y1], color='red', linewidth=4, alpha=0.6)
    ax.text((x0+x1)/2, (y0+y1)/2, f"dir{dir} (O)", color='red', fontsize=12)

# Plot new dir mappings as blue
for dir, (i, j) in dir_to_corners_new.items():
    x0, y0 = pts[i]
    x1, y1 = pts[j]
    ax.plot([x0, x1], [y0, y1], color='blue', linewidth=2, alpha=0.4, linestyle='--')

# Let's also plot directions with labels
directions = [
    (0, "East"),
    (1, "Northeast"), 
    (2, "Northwest"),
    (3, "West"), 
    (4, "Southwest"), 
    (5, "Southeast")
]

plt.axis('equal')
ax.grid(True, alpha=0.3)
plt.title("Testing Direction to Corner Mapping (Red=Old, Blue=New)")
plt.savefig('d:\\code\\immc2026-BAI\\hexdynamic\\corner_mapping_test.png', dpi=150, bbox_inches='tight')
print("Saved mapping test: corner_mapping_test.png")