
import json
from protection_pipeline import load_input, build_data_loader, compute_risk_with_riskindex

# Load input
data = load_input('base1.json')

# Compute risk
risk_map, temporal_factor_map, raw_risk_map = compute_risk_with_riskindex(data)

# Build data loader
loader = build_data_loader(data, risk_map, temporal_factor_map)

print("=== Checking get_edge_grids() for grid 58 ===")
from grid_model import HexGridModel
grid_model = HexGridModel(loader.grids)

edge_grids = grid_model.get_edge_grids()

print(f"  Total edge grids: {len(edge_grids)}")

if 58 in edge_grids:
    print(f"  ✓ Grid 58 IS in edge_grids!")
else:
    print(f"  ✗ Grid 58 IS NOT in edge_grids!")

# Let's check grid 58's neighbors
print("\n=== Checking grid 58's neighbors ===")
neighbors_58 = grid_model.get_neighbors(58)
print(f"  Neighbors of 58: {neighbors_58}")
print(f"  Count: {len(neighbors_58)}")

# Let's check grid 56
print("\n=== Checking grid 56 ===")
if 56 in edge_grids:
    print(f"  ✓ Grid 56 IS in edge_grids!")
else:
    print(f"  ✗ Grid 56 IS NOT in edge_grids!")

neighbors_56 = grid_model.get_neighbors(56)
print(f"  Neighbors of 56: {neighbors_56}")
print(f"  Count: {len(neighbors_56)}")

# Let's check grid 58's row and col coordinates
print("\n=== Checking grid 58's coordinates ===")
grid_58 = None
grid_56 = None
for grid in loader.grids:
    if grid.grid_id == 58:
        grid_58 = grid
    if grid.grid_id == 56:
        grid_56 = grid

if grid_58:
    row_58 = grid_58.r
    col_58 = grid_58.q + (row_58 // 2)
    print(f"  Grid 58: row = {row_58}, col = {col_58}")

if grid_56:
    row_56 = grid_56.r
    col_56 = grid_56.q + (row_56 // 2)
    print(f"  Grid 56: row = {row_56}, col = {col_56}")

# Get all rows and cols
print("\n=== Checking all rows and cols ===")
rows = set()
cols = set()
grid_info = {}

for grid in loader.grids:
    row = grid.r
    col = grid.q + (row // 2)
    rows.add(row)
    cols.add(col)
    grid_info[grid.grid_id] = (row, col)

min_row, max_row = min(rows), max(rows)
min_col, max_col = min(cols), max(cols)
print(f"  Rows: min={min_row}, max={max_row}")
print(f"  Cols: min={min_col}, max={max_col}")

# Now check why 58 is/is not in edge
print("\n=== Checking edge conditions for grid 58 ===")
if grid_58:
    row = grid_58.r
    col = grid_58.q + (row // 2)
    neighbors_count = len(neighbors_58)
    
    condition_1 = (neighbors_count < 6)
    condition_2 = (row == min_row or row == max_row or col == min_col or col == max_col)
    print(f"  Condition 1 (neighbors < 6): {condition_1} ({neighbors_count} neighbors)")
    print(f"  Condition 2 (row/col at boundary): {condition_2}")
    print(f"  (row: {row} ({'min' if row == min_row else 'max' if row == max_row else 'middle'}), "
          f"col: {col} ({'min' if col == min_col else 'max' if col == max_col else 'middle'}))")
